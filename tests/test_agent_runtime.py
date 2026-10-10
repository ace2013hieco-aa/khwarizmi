"""Runtime plane tests (ARCHITECTURE_DELTA §2.3 — the Agent Runtime API).

Covers the plane's whole contract, with the B-slots it owns:

- **bounded runs** — `max_ticks`, `max_proposals`, `max_model_calls_per_tick`,
  `deadline_seconds` and the declared `stop_when` policies each stop the loop;
  there is no unbounded branch, and an always-proposing model still terminates;
- **proposals only** — nothing decides a transition: the runtime emits `Intent`
  drafts through the injected Orchestration API and records the verdict, and the
  suite binds the *real* `apply_intent` to prove an admitted task lands, a
  re-emitted one is a duplicate, and an unwired kind surfaces the spine's own
  refusal as data;
- **profile allowlist refusal** — a kind outside the profile's declared
  `proposable_kinds`, an internal-only kind, a Director-only kind on a
  non-Director binding and a `requires_human_for` kind are each refused (ROLE /
  PROPOSAL) before any intent exists; configuration that declares an illegal kind
  fails to load at all;
- **identity discipline** — a draft that supplies `task_id`, `idempotency_key`,
  `proposed_by` or `project_id` is refused, while the derived ids are stable
  across runs (which is what makes a re-emitted command a duplicate, not a second
  mutation);
- **the 4 KiB cap** — an oversized draft payload refuses (`RATIONALE`) with the
  body preserved through the artifact port, an oversized delegated payload
  overflows to an artifact ref, an overflowed model body is preserved and never
  parsed, and an oversized task context refuses up front;
- **tool-failure handling** — an undeclared capability (ROLE, executor never
  called), a missing grant (default-deny at the *plane*, not bypassed here), a
  capability refusal, a failed observation and an over-bound batch; each is
  recorded, and nothing is admitted as evidence;
- **delegation (B-2)** — subagents are child tasks with derived records; a
  `PENDING` record read after a restart is classified `NO_SIGNAL` and never
  re-dispatched; `may_dispatch` is `False` on every recovery branch; completion is
  lease-generation fenced (LOCK otherwise); the store takes no private lock;
- **checkpoints + resume** — resume continues at `tick + 1`, re-emits the
  checkpointed prefix (so the spine dedupes), refuses a changed context (STALE)
  and a foreign generation without `takeover` (LOCK), and treats a terminal
  checkpoint as a no-op read;
- **crash recovery** — a real subprocess killed with `os._exit(9)` mid-run, then
  resumed, reaching the *same terminal digest* as an uninterrupted run, plus the
  `RUNNING → NO_SIGNAL → FAILED` chain;
- **concurrent agents under one lease** — two runs sharing one lease generation
  and one store set stay disjoint, terminal and fully attributed;
- **attribution-on-record (B-4)** — every proposal, refusal, checkpoint,
  delegation record and trace event carries the lease generation; a blank
  generation refuses (`LOCK`) before any call; a foreign generation cannot
  complete another generation's record;
- **projections (B-5)** — declared handler dependencies order the trace, unknown
  kinds/cycles/absent dependencies are reported as data, and the module's purity
  is checked mechanically (no `conn`, no `execute`, no writer/journal import) as
  well as behaviourally.

The plane is not an authority: nothing asserted here may decide a transition.

Scripts are keyed **per profile** in every test that asserts on a run's own
model calls, because a profile with `review.required: true` starts a *child* run
whose calls are the reviewer's, not the run's.
"""

from __future__ import annotations

import ast
import json
import os
import subprocess
import sys
import threading
from collections.abc import Mapping
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from hermes.agents.runtime import projection as projection_module
from hermes.agents.runtime import run as run_module
from hermes.agents.runtime import types as types_module
from hermes.agents.runtime.checkpoint import (
    MAX_MISSES,
    FileCheckpointStore,
    InMemoryCheckpointStore,
    apply_recovery,
    classify_recovery,
)
from hermes.agents.runtime.config import (
    ProfileConfigError,
    ProfileSpec,
    load_profile,
    load_profiles,
    parse_profile,
    parse_profile_yaml,
    profile_names,
)
from hermes.agents.runtime.delegate import (
    Delegator,
    FileDelegationStore,
    InMemoryDelegationStore,
)
from hermes.agents.runtime.projection import (
    HANDLER_DEPENDENCIES,
    events_by_tick,
    order_events,
    project_trace,
    run_summary,
)
from hermes.agents.runtime.run import (
    DRAFT_KEYS,
    RETRYABLE_MODEL_REFUSALS,
    AgentRuntime,
    output_contract_for,
    run,
)
from hermes.agents.runtime.supervisor import (
    RetryBudget,
    RunCancelToken,
    Supervisor,
)
from hermes.agents.runtime.types import (
    CONTROLLER_EMITTED_CODES,
    GATEWAY_DEFINED_CODES,
    LOCK,
    MALFORMED_PAYLOAD,
    MAX_PAYLOAD_BYTES,
    PROPOSAL,
    RATIONALE,
    ROLE,
    RUNTIME_REFUSAL_CODES,
    STALE,
    TRACE_KINDS,
    Admission,
    Checkpoint,
    DelegationRecord,
    DelegationState,
    Proposal,
    ProposalSet,
    RecoveryVerdict,
    RunLimits,
    RuntimeFormatError,
    RuntimeRefusal,
    TaskContext,
    Termination,
    TraceEvent,
    child_idempotency_key_of,
    child_task_id_of,
    digest_of,
    run_id_of,
)
from hermes.core import frozen_clock
from hermes.core.events import EventType
from hermes.core.intents import Intent, IntentKind
from hermes.core.node import AgentProfile
from hermes.core.task_status import TaskStatus
from hermes.persistence.database import connect
from hermes.persistence.migrations import migrate_to_latest
from hermes.persistence.repositories import ProjectRepository
from hermes.research.gateway import GatewayRejection, IntentResult, apply_intent
from hermes.security.boundaries import UntrustedContent
from hermes.tools.capabilities.invoke import CapabilityInvoker
from hermes.tools.capabilities.registry import CapabilityRegistry
from hermes.tools.capabilities.types import (
    Capability,
    CapabilityRefusal,
    FailureKind,
    InputField,
    InvokeRequest,
    Observation,
    RiskLevel,
    Tool,
    ToolGrant,
    ToolResult,
    ToolSet,
)
from hermes.tools.models.router import (
    ModelPlanePolicy,
    ModelProfile,
    ModelProposal,
    ModelRefusal,
    ModelRequest,
    ModelResponse,
    ModelRouter,
    RetryPolicy,
    TokenUsage,
)

STAMP = "2026-01-01T00:00:00.000000+00:00"
PROFILE_NAMES = ("critic", "experimenter", "planner", "researcher",
                 "synthesizer", "verifier")
PACKAGE = Path(run_module.__file__).resolve().parent
SRC_ROOT = PACKAGE.parents[2]
WORKTREE = SRC_ROOT.parent
DIE = "DIE"  # a script entry that kills the process (the kill-9 analogue)


# ═══════════════════════ fakes ═══════════════════════


class FakeClock:
    """A callable clock with a monotonic channel, plus the router's protocol.

    Doubles as a `hermes.tools.providers.base.Clock` (`now_utc`/`sleep`) so the
    real model router can be driven deterministically in the integration tests.
    """

    def __init__(self, start: str = STAMP) -> None:
        self._moment = datetime.fromisoformat(start)
        self._monotonic = 0.0
        self.calls = 0
        self.slept: list[float] = []

    def __call__(self) -> str:
        self.calls += 1
        return self.stamp()

    def now_utc(self) -> str:
        return self.stamp()

    def monotonic(self) -> float:
        return self._monotonic

    def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)

    def advance(self, seconds: float) -> None:
        self._moment = self._moment + timedelta(seconds=seconds)
        self._monotonic += seconds

    def stamp(self) -> str:
        return self._moment.isoformat(timespec="microseconds")


class ScriptedModel:
    """A `ModelPort` serving a script per profile, in order.

    Scripting per *profile* (rather than per call index) is what makes a resume
    comparable: a resumed run makes only the calls it has not made yet, and a
    delegated child consumes its own profile's script. A flat list is shorthand
    for "any profile" — convenient for review-free profiles, ambiguous for any
    run that delegates.
    """

    def __init__(self, scripts: Mapping[str, list[Any]] | list[Any],
                 *, on_call: Any = None) -> None:
        if isinstance(scripts, list):
            self._scripts: dict[str, list[Any]] = {"*": list(scripts)}
        else:
            self._scripts = {name: list(items) for name, items in scripts.items()}
        self.calls: list[ModelRequest] = []
        self._on_call = on_call

    @property
    def call_count(self) -> int:
        return len(self.calls)

    def calls_for(self, profile: str) -> int:
        return sum(1 for request in self.calls if request.profile == profile)

    def invoke(self, request: ModelRequest) -> Any:
        self.calls.append(request)
        script = self._scripts.get(request.profile)
        if script is None:
            script = self._scripts.get("*")
        if not script:
            return _model_refusal(MALFORMED_PAYLOAD,
                                  f"no scripted response for {request.profile!r}")
        entry = script.pop(0)
        if self._on_call is not None:
            self._on_call(request)
        if entry == DIE:
            os._exit(9)
        if callable(entry):
            entry = entry(request)
        return entry


class FakeApplier:
    """The Orchestration API fake — using the *real* spine value types.

    Identity is content-addressed exactly as the spine does it: the same intent
    comes back `duplicate=True`, which is what makes "resume re-emits and the
    spine dedupes" testable without a database.
    """

    def __init__(self, *, refuse: Mapping[str, str] | None = None) -> None:
        self.calls: list[Intent] = []
        self._seen: dict[str, str] = {}
        self._refuse = dict(refuse or {})

    def __call__(self, intent: Intent) -> IntentResult:
        self.calls.append(intent)
        code = self._refuse.get(intent.kind.value)
        if code:
            raise GatewayRejection(intent.kind, code,
                                   f"{intent.kind.value} refused by the test spine")
        key = digest_of({"kind": intent.kind.value, "project": intent.project_id,
                         "payload": dict(intent.payload)})
        if key in self._seen:
            return IntentResult(kind=intent.kind, entity_type="task",
                                entity_id=self._seen[key], duplicate=True,
                                row={}, event_type="TaskCreated")
        entity = "task_" + key[:16]
        self._seen[key] = entity
        return IntentResult(kind=intent.kind, entity_type="task", entity_id=entity,
                            duplicate=False, row={}, event_type="TaskCreated")

    def kinds(self) -> tuple[str, ...]:
        return tuple(intent.kind.value for intent in self.calls)


class FakeArtifacts:
    """The artifact-overflow port: bytes in, an opaque handle out."""

    def __init__(self) -> None:
        self.stored: dict[str, bytes] = {}
        self.calls: list[int] = []

    def store(self, body: bytes, *, media_type: str) -> str:
        self.calls.append(len(body))
        ref = "artifact/" + digest_of({"media": media_type,
                                       "size": len(body)})[:16]
        self.stored[ref] = bytes(body)
        return ref

    def dereference(self, ref: str) -> bytes:
        return self.stored[ref]


class SpyCapabilities:
    """A `CapabilityPort` that records requests and returns scripted results."""

    def __init__(self, results: list[Any] | None = None) -> None:
        self.requests: list[InvokeRequest] = []
        self._results = list(results or [])

    def invoke(self, request: InvokeRequest) -> Any:
        self.requests.append(request)
        if self._results:
            return self._results.pop(0)
        return _ok_observation(request.capability_id)


class LiveProvider:
    """A minimal live `ModelProvider` — the real router's transport."""

    provider_id = "alpha"

    def __init__(self, responses: list[ModelResponse],
                 profiles: tuple[ModelProfile, ...]) -> None:
        self._responses = list(responses)
        self._profiles = profiles
        self.calls: list[Any] = []

    def describe(self) -> tuple[ModelProfile, ...]:
        return self._profiles

    def invoke(self, call: Any) -> ModelResponse:
        self.calls.append(call)
        return self._responses.pop(0)

    def stream(self, call: Any) -> tuple[Any, ...]:
        return ()


def _ok_observation(capability_id: str, *,
                    artifacts: tuple[str, ...] = ("artifacts/observation-1",)
                    ) -> Observation:
    return Observation(capability_id=capability_id, status="OK",
                       payload=UntrustedContent(text="observation body",
                                                origin=f"capability.{capability_id}",
                                                ref="ref-1"),
                       artifacts=artifacts)


def _failed_observation(capability_id: str) -> Observation:
    return Observation(capability_id=capability_id, status="FAILED",
                       failure=FailureKind.TOOL_ERROR, detail="boom")


def _model_refusal(code: str, detail: str = "refused") -> ModelRefusal:
    return ModelRefusal(code=code, detail=detail)


def _proposal(structured: Mapping[str, Any], *, provider: str = "alpha",
              model: str = "m1", overflow: Any = None) -> ModelProposal:
    return ModelProposal(provider_id=provider, model_id=model, tier="research",
                         profile="scripted", lease_generation="gen-1",
                         structured=dict(structured), overflow=overflow)


def _draft(kind: str = "INSERT_TASK", *, rationale: str = "because",
           payload: Mapping[str, Any] | None = None) -> ModelProposal:
    return _proposal({"kind": kind, "rationale": rationale,
                      "payload": dict(payload or {})})


def _silent(rationale: str = "nothing to propose") -> ModelProposal:
    """A model output with no proposal in it at all."""
    return _proposal({"rationale": rationale})


# ═══════════════════════ helpers ═══════════════════════


def _ctx(**overrides: Any) -> TaskContext:
    fields: dict[str, Any] = {
        "task_id": "task-root",
        "project_id": "p1",
        "lease_generation": "gen-1",
    }
    fields.update(overrides)
    return TaskContext(**fields)


def _one_tick(**overrides: Any) -> TaskContext:
    """A context bounded to a single tick — one model output, one tick's refusals.

    Most single-output tests want exactly one turn of the loop: `max_ticks: 1`
    keeps a refusal-only tick from being followed by a second, empty model call.
    """
    fields: dict[str, Any] = {"limits": RunLimits(max_ticks=1)}
    fields.update(overrides)
    return _ctx(**fields)


def _runtime(model: Any, *, applier: Any = None, **overrides: Any) -> AgentRuntime:
    fields: dict[str, Any] = {
        "model": model,
        "orchestration": applier if applier is not None else FakeApplier(),
        "profiles": load_profiles(),
    }
    fields.update(overrides)
    return AgentRuntime(**fields)


def _own(result: ProposalSet, rationale: str = "because") -> list[Proposal]:
    """The run's own proposals — excluding the child task a review delegates.

    A profile that requires review emits a second `INSERT_TASK` for the reviewer
    child task; `_own` isolates the drafts the model actually produced.
    """
    return [proposal for proposal in result.proposals
            if proposal.rationale == rationale]


def _untrusted(text: str = "context") -> UntrustedContent:
    return UntrustedContent(text=text, origin="test", ref="ref-1")


def _temp_profile(directory: Path, name: str, body: str) -> ProfileSpec:
    (directory / f"{name}.yaml").write_text(body, encoding="utf-8")
    return load_profile(name, directory=directory)


def _module_source(module: Any) -> str:
    return Path(module.__file__).read_text(encoding="utf-8")


def _package_sources() -> dict[str, str]:
    return {path.name: path.read_text(encoding="utf-8")
            for path in sorted(PACKAGE.glob("*.py"))}


def _direct_hermes_imports(source: str) -> set[str]:
    found: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names
                         if alias.name.startswith("hermes"))
        elif (isinstance(node, ast.ImportFrom) and node.module
                and node.module.startswith("hermes")):
            found.add(node.module)
    return found


def _referenced_names(source: str) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Name):
            names.add(node.id)
        elif isinstance(node, ast.Attribute):
            names.add(node.attr)
        elif isinstance(node, ast.keyword) and node.arg:
            names.add(node.arg)
    return names


def _tool_capability_invoker(executed: list[Any], *,
                             capability_id: str = "source_search",
                             tool_id: str = "t_search") -> CapabilityInvoker:
    registry = CapabilityRegistry(allowlist=frozenset({capability_id}))
    registry.register_tool(Tool(tool_id=tool_id, summary="declared tool",
                                inputs=(InputField("query", "string"),),
                                risk=RiskLevel.LOW))
    registry.register_capability(Capability(capability_id=capability_id,
                                            tool_id=tool_id, summary="capability"))
    registry.register_tool_set(ToolSet(set_id="research_tools",
                                       capability_ids=(capability_id,)))

    def executor(arguments: Mapping[str, Any], context: Any) -> ToolResult:
        executed.append(dict(arguments))
        return ToolResult(payload="found 3 sources",
                          artifacts=("artifacts/observation-1",))

    return CapabilityInvoker(registry=registry, implementations={tool_id: executor},
                             clock=FakeClock())


def _research_grant(profile: str = "RESEARCHER") -> ToolGrant:
    return ToolGrant(grant_id="g1", profile=profile,
                     tool_set_ids=frozenset({"research_tools"}), max_risk="HIGH")


def _base_document() -> dict[str, Any]:
    return {
        "version": "1",
        "name": "solo",
        "role": "a test profile",
        "agent_profile": "RESEARCHER",
        "model_policy": {"tier": "research"},
        "tools": ["a", "b"],
        "authority": {"proposable_kinds": ["INSERT_TASK"],
                      "allowed_capabilities": ["a"]},
        "termination": {"max_ticks": 2, "max_proposals": 2,
                        "stop_when": "proposals_raised"},
        "review": {"required": False},
    }


def _base_document_yaml(*, name: str = "solo", reviewer: str = "") -> str:
    review = (f"review:\n  reviewer_profile: {reviewer}\n  required: true\n"
              if reviewer else "review:\n  required: false\n")
    return (
        "version: \"1\"\n"
        f"name: {name}\n"
        "role: a test profile\n"
        "agent_profile: RESEARCHER\n"
        "model_policy:\n"
        "  tier: research\n"
        "tools: [a]\n"
        "authority:\n"
        "  proposable_kinds:\n"
        "    - INSERT_TASK\n"
        "  allowed_capabilities: [a]\n"
        "termination:\n"
        "  max_ticks: 2\n"
        "  max_proposals: 2\n"
        "  stop_when: proposals_raised\n"
        + review)


def _authority_document_error(kinds: list[str],
                              human_required: list[str] | None = None) -> None:
    document = _base_document()
    document["authority"]["proposable_kinds"] = kinds
    if human_required is not None:
        document["authority"]["requires_human_for"] = human_required
    parse_profile(document)


# ═══════════════════════ module invariants ═══════════════════════


class TestModuleInvariants:
    def test_package_reexports_nothing(self) -> None:
        import hermes.agents.runtime as package

        assert package.__all__ == []

    def test_carried_public_symbols_are_exported_or_privatized(self) -> None:
        # The carried P2s (R2/R3, re-confirmed by R4 item 9): a public,
        # module-level callable that no `__all__` maps is an unmapped extra on a
        # plane's surface. Export-and-map is the fix; a leading underscore is the
        # other. The rule has a *target* here precisely because both modules
        # declare an `__all__`.
        from hermes.tools.capabilities import envelope
        from hermes.tools.models import router

        for module in (router, envelope):
            assert isinstance(module.__all__, list), module.__name__
            assert module.__all__, f"{module.__name__} declares no export list"
        for module, name in ((router, "fixture_from_response"),
                             (envelope, "record_value"),
                             (envelope, "redaction_gaps")):
            assert callable(getattr(module, name))
            assert name.startswith("_") or name in module.__all__, (
                f"{module.__name__}.{name} is public but not in __all__")

    def test_refusal_codes_are_exactly_the_existing_vocabulary(self) -> None:
        assert frozenset(
            {ROLE, LOCK, PROPOSAL, RATIONALE, STALE, MALFORMED_PAYLOAD}) == RUNTIME_REFUSAL_CODES

    def test_refusal_code_provenance_is_rederived_from_source(self) -> None:
        gateway = (SRC_ROOT / "hermes" / "research" / "gateway.py").read_text(
            encoding="utf-8")
        controller = (SRC_ROOT / "hermes" / "research" / "controller.py"
                      ).read_text(encoding="utf-8")
        for code in sorted(GATEWAY_DEFINED_CODES):
            assert f'{code} = "{code}"' in gateway, code
        for code in sorted(CONTROLLER_EMITTED_CODES):
            assert f'"{code}"' in controller, code
            assert f'{code} = "{code}"' not in gateway, code
        assert GATEWAY_DEFINED_CODES | CONTROLLER_EMITTED_CODES == (
            RUNTIME_REFUSAL_CODES)

    def test_payload_cap_is_the_event_payload_cap(self) -> None:
        source = (SRC_ROOT / "hermes" / "persistence"
                  / "event_validation.py").read_text(encoding="utf-8")
        assert "DEFAULT_PAYLOAD_MAX_BYTES = 4096" in source
        assert MAX_PAYLOAD_BYTES == 4096

    def test_trace_kinds_are_not_event_types(self) -> None:
        assert not (set(TRACE_KINDS) & {member.value for member in EventType})

    def test_no_plane_module_names_a_profile_that_a_class_could_implement(self) -> None:
        for name, source in _package_sources().items():
            for node in ast.walk(ast.parse(source)):
                if isinstance(node, (ast.ClassDef, ast.FunctionDef)):
                    assert node.name not in PROFILE_NAMES, f"{name}: {node.name}"

    def test_direct_hermes_imports_stay_inside_the_allowed_direction(self) -> None:
        allowed = ("hermes.core", "hermes.security.boundaries", "hermes.tools.models",
                   "hermes.tools.capabilities", "hermes.agents.runtime")
        for name, source in _package_sources().items():
            for module in _direct_hermes_imports(source):
                assert module.startswith(allowed), f"{name}: {module}"

    def test_no_persistence_sql_or_journal_writer_anywhere(self) -> None:
        banned_imports = ("hermes.persistence", "hermes.research", "sqlite3",
                          "hermes.artifacts", "hermes.recovery", "hermes.vault")
        banned_names = {"conn", "cursor", "executescript", "_append_event_to_db",
                        "repositories", "Lock", "RLock", "fcntl", "msvcrt",
                        "execute"}
        for name, source in _package_sources().items():
            for module in _direct_hermes_imports(source):
                for banned in banned_imports:
                    assert not module.startswith(banned), f"{name}: {module}"
            offenders = sorted(_referenced_names(source) & banned_names)
            assert not offenders, f"{name}: {offenders}"
            assert "BEGIN IMMEDIATE" not in source, name

    def test_no_module_declares_an_ambient_lease_setter(self) -> None:
        # B-4: attribution comes from the lease generation, never from a settable
        # ambient variable (the source's `set_execution_uuid` is the counter-example).
        for name, source in _package_sources().items():
            assert "set_execution_uuid" not in source, name
            assert "execution_uuid" not in source, name
            for node in ast.walk(ast.parse(source)):
                if isinstance(node, ast.FunctionDef):
                    assert not node.name.startswith("set_lease"), f"{name}: {node.name}"

    def test_profile_names_are_files_not_code(self) -> None:
        assert profile_names() == PROFILE_NAMES
        for name in PROFILE_NAMES:
            assert (PACKAGE / "profiles" / f"{name}.yaml").is_file()


# ═══════════════════════ configuration ═══════════════════════


class TestProfileConfiguration:
    def test_every_profile_loads_and_binds_a_known_agent_profile(self) -> None:
        specs = load_profiles()
        assert sorted(specs) == list(PROFILE_NAMES)
        known = {member.value for member in AgentProfile}
        for spec in specs.values():
            assert spec.agent_profile in known
            assert spec.model_policy.tier
            assert spec.termination.max_ticks >= 1
            assert spec.termination.max_proposals >= 1

    def test_declared_kinds_are_llm_proposable_and_never_internal(self) -> None:
        proposable = IntentKind.llm_proposable()
        internal = IntentKind.internal_only()
        for spec in load_profiles().values():
            for name in spec.authority.proposable_kinds:
                assert IntentKind(name) in proposable, (spec.name, name)
                assert IntentKind(name) not in internal, (spec.name, name)
            for name in spec.authority.requires_human_for:
                assert IntentKind(name) in proposable

    def test_requires_human_for_is_disjoint_from_proposable(self) -> None:
        for spec in load_profiles().values():
            assert not (set(spec.authority.proposable_kinds)
                        & set(spec.authority.requires_human_for))

    def test_director_only_authority_is_declared_only_by_the_director_binding(self) -> None:
        for spec in load_profiles().values():
            if IntentKind.PROPOSE_RESEARCH_PROGRAM.value in (
                    spec.authority.proposable_kinds):
                assert spec.agent_profile == AgentProfile.DIRECTOR.value
                assert spec.authority.director_only

    def test_capabilities_must_be_declared_tools(self) -> None:
        for spec in load_profiles().values():
            assert set(spec.authority.allowed_capabilities) <= set(spec.tools)

    def test_reviewers_exist_and_review_is_asymmetric(self) -> None:
        specs = load_profiles()
        for spec in specs.values():
            if spec.review.reviewer_profile:
                assert spec.review.reviewer_profile in specs
        assert specs["critic"].review.required is False
        assert specs["researcher"].review.reviewer_profile == "critic"

    def test_output_contract_is_built_from_the_declared_fields(self) -> None:
        contract = output_contract_for(load_profiles()["researcher"])
        names = [field.name for field in contract.fields]
        assert names[0] == "kind"
        assert contract.rationale_field in names
        assert contract.allows_decision is False
        assert "tool_calls" in names
        assert "delegations" not in names

    def test_unknown_structured_field_fails_the_contract(self) -> None:
        spec = load_profiles()["researcher"]
        broken = ProfileSpec(
            name=spec.name, role=spec.role, agent_profile=spec.agent_profile,
            model_policy=type(spec.model_policy)(tier="t",
                                                 structured_fields=("bogus",)),
            tools=spec.tools, authority=spec.authority, schemas=spec.schemas,
            termination=spec.termination, review=spec.review)
        with pytest.raises(ProfileConfigError):
            output_contract_for(broken)

    # ── the YAML subset ──

    def test_parser_handles_the_declared_subset(self) -> None:
        document = parse_profile_yaml(
            "# a comment\n"
            "name: researcher\n"
            "quoted: \"a # b\"\n"
            "flag: true\n"
            "count: 12\n"
            "ratio: 1.5\n"
            "nothing: null\n"
            "inline: [a, b, c]\n"
            "empty: []\n"
            "nested:\n"
            "  inner: 3\n"
            "list:\n"
            "  - one\n"
            "  - two\n",
            source="t.yaml")
        assert document["name"] == "researcher"
        assert document["quoted"] == "a # b"
        assert document["flag"] is True
        assert document["count"] == 12
        assert document["ratio"] == 1.5
        assert document["nothing"] is None
        assert document["inline"] == ["a", "b", "c"]
        assert document["empty"] == []
        assert document["nested"] == {"inner": 3}
        assert document["list"] == ["one", "two"]

    @pytest.mark.parametrize("document", [
        "name: &anchor x\n",
        "name: *alias\n",
        "name: |\n  block\n",
        "name: {a: b}\n",
        "name: !!str x\n",
        "name: a\nname: b\n",
        "name:\n  a: 1\n   b: 2\n",
        "\tname: x\n",
        "---\nname: x\n",
        "name: \"unterminated\n",
        "name: [a, [b]]\n",
        "list:\n  - a: 1\n",
        "name: x\n  bad: indent\n",
    ])
    def test_parser_refuses_what_it_cannot_read(self, document: str) -> None:
        with pytest.raises(ProfileConfigError):
            parse_profile_yaml(document, source="t.yaml")

    def test_parser_refuses_an_empty_document(self) -> None:
        with pytest.raises(ProfileConfigError):
            parse_profile_yaml("\n# only a comment\n", source="t.yaml")

    def test_comments_are_quote_aware(self) -> None:
        document = parse_profile_yaml("role: \"keep # this\"  # drop this\n")
        assert document["role"] == "keep # this"

    def test_quoted_scalar_refuses_an_escaped_quote(self) -> None:
        with pytest.raises(ProfileConfigError):
            parse_profile_yaml("role: \"a\\\"b\"\n", source="t.yaml")

    # ── validation ──

    def test_unknown_top_level_key_refuses(self) -> None:
        with pytest.raises(ProfileConfigError) as error:
            parse_profile({"name": "x", "role": "r",
                           "agent_profile": "RESEARCHER", "bogus": 1})
        assert "unknown keys" in str(error.value)

    def test_declaring_an_internal_only_kind_refuses_at_load(self) -> None:
        with pytest.raises(ProfileConfigError) as error:
            _authority_document_error(["ADMIT_TASK"])
        assert "internal-only" in str(error.value)

    def test_unknown_kind_name_refuses_at_load(self) -> None:
        with pytest.raises(ProfileConfigError):
            _authority_document_error(["NOT_A_KIND"])

    def test_kind_both_proposable_and_human_required_refuses(self) -> None:
        with pytest.raises(ProfileConfigError):
            _authority_document_error(["ABANDON"], human_required=["ABANDON"])

    def test_unknown_agent_profile_refuses(self) -> None:
        document = _base_document()
        document["agent_profile"] = "WIZARD"
        with pytest.raises(ProfileConfigError):
            parse_profile(document)

    def test_undeclared_capability_refuses(self) -> None:
        document = _base_document()
        document["tools"] = ["a"]
        document["authority"]["allowed_capabilities"] = ["b"]
        with pytest.raises(ProfileConfigError):
            parse_profile(document)

    def test_director_only_on_a_non_director_binding_refuses(self) -> None:
        document = _base_document()
        document["authority"]["director_only"] = True
        with pytest.raises(ProfileConfigError):
            parse_profile(document)

    def test_unknown_model_policy_key_refuses(self) -> None:
        document = _base_document()
        document["model_policy"]["temperature"] = 0.5
        with pytest.raises(ProfileConfigError):
            parse_profile(document)

    @pytest.mark.parametrize("field,value", [
        ("max_ticks", 0), ("max_proposals", 0), ("stop_when", "whenever"),
        ("deadline_seconds", -1), ("max_tool_calls", -1),
        ("max_model_calls_per_tick", 0),
    ])
    def test_incoherent_termination_refuses(self, field: str, value: Any) -> None:
        document = _base_document()
        document["termination"][field] = value
        with pytest.raises(ProfileConfigError):
            parse_profile(document)

    def test_review_required_without_a_reviewer_refuses(self) -> None:
        document = _base_document()
        document["review"] = {"required": True}
        with pytest.raises(ProfileConfigError):
            parse_profile(document)

    def test_unknown_reviewer_refuses_at_collection_load(self,
                                                         tmp_path: Path) -> None:
        (tmp_path / "solo.yaml").write_text(_base_document_yaml(reviewer="ghost"),
                                            encoding="utf-8")
        with pytest.raises(ProfileConfigError) as error:
            load_profiles(directory=tmp_path)
        assert "not a declared profile" in str(error.value)

    def test_file_name_and_declared_name_must_agree(self, tmp_path: Path) -> None:
        (tmp_path / "solo.yaml").write_text(_base_document_yaml(name="other"),
                                            encoding="utf-8")
        with pytest.raises(ProfileConfigError):
            load_profile("solo", directory=tmp_path)

    def test_a_missing_profile_directory_refuses(self, tmp_path: Path) -> None:
        with pytest.raises(ProfileConfigError):
            load_profiles(directory=tmp_path / "absent")

    def test_review_complete_needs_a_declared_review(self, tmp_path: Path) -> None:
        # The policy stops a run once there is something for its *review* to
        # consider: without a declared review it is incoherent, so it is refused
        # at load rather than accepted as a knob that could not mean anything.
        body = _base_document_yaml().replace(
            "stop_when: proposals_raised", "stop_when: review_complete")
        with pytest.raises(ProfileConfigError):
            _temp_profile(tmp_path, "solo", body)
        reviewed = _base_document_yaml(name="reviewed", reviewer="critic").replace(
            "stop_when: proposals_raised", "stop_when: review_complete")
        spec = _temp_profile(tmp_path, "reviewed", reviewed)
        assert spec.termination.stop_when == "review_complete"
        assert spec.review.required is True

    def test_a_new_profile_is_configuration_only(self, tmp_path: Path) -> None:
        # §5's archetype: "New agent profile (e.g. a curator profile)" — added as
        # a file, with no code change anywhere.
        (tmp_path / "curator.yaml").write_text(
            "version: \"1\"\n"
            "name: curator\n"
            "role: knowledge curation\n"
            "agent_profile: DIRECTOR\n"
            "model_policy:\n"
            "  tier: synthesis\n"
            "  structured_fields: [proposals]\n"
            "tools: [artifact_store]\n"
            "authority:\n"
            "  proposable_kinds:\n"
            "    - INSERT_TASK\n"
            "  director_only: false\n"
            "  allowed_capabilities: [artifact_store]\n"
            "termination:\n"
            "  max_ticks: 2\n"
            "  max_proposals: 2\n"
            "  stop_when: proposals_raised\n"
            "review:\n"
            "  required: false\n",
            encoding="utf-8")
        specs = load_profiles(directory=tmp_path)
        assert list(specs) == ["curator"]
        result = _runtime(ScriptedModel({"curator": [_draft()]}),
                          profiles=specs).run("curator", _one_tick())
        assert result.state == TaskStatus.SUCCEEDED.value
        assert [proposal for proposal in result.proposals
                if proposal.was_admitted()]


# ═══════════════════════ bounded runs ═══════════════════════


class TestBoundedRun:
    def test_a_single_proposal_run_is_bounded_and_admitted(self) -> None:
        applier = FakeApplier()
        model = ScriptedModel({"researcher": [
            _draft(payload={"intent": "investigate"})]})
        runtime = _runtime(model, applier=applier)
        result = runtime.run("researcher", _one_tick())
        assert result.state == TaskStatus.SUCCEEDED.value
        assert result.termination == Termination.STOP_WHEN.value
        assert result.ticks == 1
        assert model.calls_for("researcher") == 1
        own = _own(result)
        assert len(own) == 1
        assert own[0].admission == Admission.ADMITTED.value
        assert own[0].admitted_entity_id
        assert applier.calls[0].kind is IntentKind.INSERT_TASK
        # researcher declares review.required: the review is a *child task*.
        records = runtime.delegation_records(run_id=result.run_id)
        assert [record.profile for record in records] == ["critic"]
        assert records[0].state == DelegationState.DONE.value

    def test_tick_limit_stops_an_always_proposing_model(self) -> None:
        # critic's policy is `no_proposals`; a model that keeps proposing can only
        # be stopped by the tick bound — which is the point of the bound.
        model = ScriptedModel([_draft("ABANDON", rationale=f"r{i}")
                               for i in range(10)])
        result = _runtime(model).run("critic", _ctx())
        assert result.termination == Termination.TICK_LIMIT.value
        assert result.ticks == load_profiles()["critic"].termination.max_ticks
        assert model.call_count == result.ticks
        assert len(result.proposals) == result.ticks

    def test_review_complete_stops_the_run_once_the_plan_is_raised(self) -> None:
        # planner declares `stop_when: review_complete`. Before the policy had a
        # handler the declaration was inert and the run fell through to the tick
        # limit (R4 probe 5d).
        scripts = {"planner": [_draft("BRANCH", payload={"x": 1}),
                               _draft("BRANCH", payload={"x": 2})],
                   "verifier": [_draft("REQUEST_REPLICATION", payload={})]}
        model = ScriptedModel(scripts)
        runtime = _runtime(model)
        result = runtime.run("planner", _ctx())
        assert result.state == TaskStatus.SUCCEEDED.value
        assert result.termination == Termination.STOP_WHEN.value
        assert result.ticks == 1
        assert model.calls_for("planner") == 1
        # The review is still the close act that follows the stop.
        assert [record.profile for record in runtime.delegation_records(
            run_id=result.run_id)] == ["verifier"]

    def test_proposal_limit_stops_the_run(self, tmp_path: Path) -> None:
        body = (_base_document_yaml(name="greedy")
                .replace("stop_when: proposals_raised", "stop_when: no_proposals")
                .replace("max_ticks: 2", "max_ticks: 5"))
        spec = _temp_profile(tmp_path, "greedy", body)
        model = ScriptedModel([_draft(rationale=f"r{i}") for i in range(5)])
        result = _runtime(model, profiles={"greedy": spec}).run("greedy", _ctx())
        assert result.termination == Termination.PROPOSAL_LIMIT.value
        assert len(result.proposals) >= 2

    def test_converged_policy_stops_on_a_repeated_draft(self,
                                                        tmp_path: Path) -> None:
        body = (_base_document_yaml(name="converging")
                .replace("stop_when: proposals_raised", "stop_when: converged")
                .replace("max_ticks: 2", "max_ticks: 5"))
        spec = _temp_profile(tmp_path, "converging", body)
        same = {"kind": "INSERT_TASK", "rationale": "same", "payload": {"x": 1}}
        model = ScriptedModel([_proposal(same) for _ in range(5)])
        result = _runtime(model, profiles={"converging": spec}).run(
            "converging", _ctx())
        assert result.termination == Termination.STOP_WHEN.value
        assert result.ticks == 2

    def test_no_proposals_policy_stops_when_the_model_is_silent(self) -> None:
        result = _runtime(ScriptedModel([_silent()])).run("critic", _ctx())
        assert result.termination == Termination.NO_PROPOSALS.value
        assert result.proposals == ()
        assert result.state == TaskStatus.SUCCEEDED.value

    def test_an_unknown_profile_refuses_without_a_model_call(self) -> None:
        model = ScriptedModel([_draft()])
        result = _runtime(model).run("ghost", _ctx())
        assert result.state == TaskStatus.FAILED.value
        assert result.termination == MALFORMED_PAYLOAD
        assert model.call_count == 0
        assert result.refusal_codes() == (MALFORMED_PAYLOAD,)

    def test_a_blank_lease_refuses_before_any_call(self) -> None:
        model = ScriptedModel([_draft()])
        result = _runtime(model).run("researcher", _ctx(lease_generation="  "))
        assert result.termination == LOCK
        assert model.call_count == 0
        assert result.refusal_codes() == (LOCK,)

    def test_a_missing_task_or_project_refuses(self) -> None:
        model = ScriptedModel([_draft()])
        result = _runtime(model).run("researcher", _ctx(project_id=""))
        assert result.termination == MALFORMED_PAYLOAD
        assert model.call_count == 0

    def test_an_oversized_task_payload_refuses(self) -> None:
        model = ScriptedModel([_draft()])
        context = _ctx(payload={"blob": "x" * (MAX_PAYLOAD_BYTES + 10)})
        result = _runtime(model).run("researcher", context)
        assert result.termination == RATIONALE
        assert model.call_count == 0

    def test_oversized_inline_context_refuses(self) -> None:
        model = ScriptedModel([_draft()])
        context = _ctx(context=(_untrusted("x" * (MAX_PAYLOAD_BYTES + 10)),))
        result = _runtime(model).run("researcher", context)
        assert result.termination == RATIONALE
        assert model.call_count == 0

    def test_run_id_is_derived_by_rule(self) -> None:
        result = _runtime(ScriptedModel({"researcher": [_draft()]})).run(
            "researcher", _one_tick())
        assert result.run_id == run_id_of("researcher", "task-root", "p1", 1)
        assert result.run_id.startswith("run_")

    def test_an_explicit_run_id_is_honoured(self) -> None:
        result = _runtime(ScriptedModel({"researcher": [_draft()]})).run(
            "researcher", _one_tick(run_id="run_given"))
        assert result.run_id == "run_given"

    def test_the_module_level_run_builds_a_runtime(self) -> None:
        applier = FakeApplier()
        result = run("researcher", _one_tick(),
                     model=ScriptedModel({"researcher": [_draft()]}),
                     orchestration=applier, profiles=load_profiles())
        assert result.state == TaskStatus.SUCCEEDED.value
        assert applier.calls

    def test_a_retryable_refusal_is_retried_within_the_budget(self) -> None:
        # researcher declares max_model_calls_per_tick: 2 → exactly one retry.
        model = ScriptedModel({"researcher": [
            _model_refusal(RATIONALE, "no rationale"), _draft()]})
        result = _runtime(model).run("researcher", _one_tick())
        assert model.calls_for("researcher") == 2
        assert result.state == TaskStatus.SUCCEEDED.value

    def test_a_request_side_refusal_is_not_retried(self) -> None:
        model = ScriptedModel({"researcher": [
            _model_refusal(MALFORMED_PAYLOAD, "bad request"), _draft()]})
        result = _runtime(model).run("researcher", _one_tick())
        assert model.calls_for("researcher") == 1
        assert result.termination == Termination.MODEL_REFUSED.value
        assert result.refusal_codes() == (MALFORMED_PAYLOAD,)

    def test_a_garbage_model_port_answer_is_a_port_failure(self) -> None:
        result = _runtime(ScriptedModel({"researcher": ["not a proposal"]})).run(
            "researcher", _one_tick())
        assert result.termination == Termination.PORT_FAILURE.value
        assert result.refusal_codes() == (MALFORMED_PAYLOAD,)

    def test_the_retry_budget_is_deterministic_and_bounded(self) -> None:
        budget = RetryBudget(max_retries=3, base_delay_seconds=0.5)
        assert budget.delays() == (0.5, 1.0, 2.0)
        assert budget.allows(3) is True
        assert budget.allows(4) is False

    def test_retryable_matrix_is_the_declared_one(self) -> None:
        assert frozenset({RATIONALE}) == RETRYABLE_MODEL_REFUSALS


# ═══════════════════════ authority ═══════════════════════


class TestProposalAuthority:
    def _run_one(self, proposal: ModelProposal, profile: str = "researcher"
                 ) -> tuple[ProposalSet, FakeApplier]:
        applier = FakeApplier()
        runtime = _runtime(ScriptedModel({profile: [proposal]}), applier=applier)
        return runtime.run(profile, _one_tick()), applier

    def test_a_kind_outside_the_allowlist_refuses_role(self) -> None:
        result, applier = self._run_one(_draft("BRANCH"))
        assert applier.calls == []
        assert result.proposals == ()
        assert result.refusal_codes() == (ROLE,)
        assert "outside" in result.refusals[0].detail

    def test_an_internal_only_kind_refuses(self) -> None:
        result, applier = self._run_one(_draft("ADMIT_TASK"))
        assert applier.calls == []
        assert result.refusal_codes() == (ROLE,)
        assert "internal-only" in result.refusals[0].detail

    def test_a_director_only_kind_refuses_on_a_non_director_profile(self) -> None:
        result, applier = self._run_one(_draft("PROPOSE_RESEARCH_PROGRAM"),
                                        profile="verifier")
        assert applier.calls == []
        assert result.refusal_codes() == (ROLE,)

    def test_a_director_only_kind_is_allowed_on_the_director_binding(self) -> None:
        result, applier = self._run_one(_draft("PROPOSE_RESEARCH_PROGRAM"),
                                        profile="synthesizer")
        assert applier.kinds()[0] == "PROPOSE_RESEARCH_PROGRAM"
        assert result.proposals[0].was_admitted()

    def test_a_requires_human_kind_refuses_as_proposal(self) -> None:
        result, applier = self._run_one(_draft("PROPOSE_GATE_OVERRIDE"))
        assert applier.calls == []
        assert result.refusal_codes() == (PROPOSAL,)
        assert "HumanDecisionReceived" in result.refusals[0].detail

    def test_an_unknown_kind_name_refuses_as_malformed(self) -> None:
        result, _applier = self._run_one(_draft("NOT_A_KIND"))
        assert result.refusal_codes() == (MALFORMED_PAYLOAD,)

    @pytest.mark.parametrize("key", ["task_id", "idempotency_key",
                                     "proposed_by", "project_id"])
    def test_a_draft_may_not_author_an_identity(self, key: str) -> None:
        result, applier = self._run_one(_draft(payload={key: "mine"}))
        assert applier.calls == []
        assert result.refusal_codes() == (MALFORMED_PAYLOAD,)

    def test_a_draft_without_a_rationale_refuses(self) -> None:
        result, _applier = self._run_one(
            _proposal({"kind": "INSERT_TASK", "payload": {}}))
        assert result.refusal_codes() == (RATIONALE,)

    def test_unknown_structured_keys_refuse(self) -> None:
        result, _applier = self._run_one(_proposal({
            "kind": "INSERT_TASK", "rationale": "r", "payload": {},
            "verdict": "SUPPORTED"}))
        assert result.refusal_codes() == (MALFORMED_PAYLOAD,)

    def test_both_proposal_forms_at_once_refuse(self) -> None:
        result, _applier = self._run_one(_proposal({
            "kind": "INSERT_TASK", "rationale": "r", "payload": {},
            "proposals": [{"kind": "INSERT_TASK", "rationale": "r"}]}))
        assert result.refusal_codes() == (MALFORMED_PAYLOAD,)

    def test_a_non_list_proposals_section_refuses(self) -> None:
        result, _applier = self._run_one(_proposal({"rationale": "r",
                                                    "proposals": {"kind": "x"}}))
        assert result.refusal_codes() == (MALFORMED_PAYLOAD,)

    def test_a_draft_carrying_an_unknown_key_refuses(self) -> None:
        result, _applier = self._run_one(_proposal({
            "proposals": [{"kind": "INSERT_TASK", "rationale": "r", "extra": 1}]}))
        assert result.refusal_codes() == (MALFORMED_PAYLOAD,)

    def test_a_non_mapping_payload_refuses(self) -> None:
        result, _applier = self._run_one(_proposal({
            "kind": "INSERT_TASK", "rationale": "r", "payload": "text"}))
        assert result.refusal_codes() == (MALFORMED_PAYLOAD,)

    def test_draft_keys_are_the_closed_schema(self) -> None:
        assert frozenset({"kind", "rationale", "payload"}) == DRAFT_KEYS

    def test_derived_insert_task_identity_is_stable_across_runs(self) -> None:
        applier = FakeApplier()
        model = ScriptedModel({"researcher": [
            _draft(payload={"spec": {"a": 1}}),
            _draft(payload={"spec": {"a": 1}})]})
        runtime = _runtime(model, applier=applier)
        first = runtime.run("researcher", _one_tick())
        second = runtime.run("researcher", _one_tick())
        first_payload = _own(first)[0].intent.payload
        second_payload = _own(second)[0].intent.payload
        assert first_payload["task_id"] == second_payload["task_id"]
        assert first_payload["idempotency_key"] == second_payload["idempotency_key"]
        assert _own(first)[0].admission == Admission.ADMITTED.value
        assert _own(second)[0].admission == Admission.DUPLICATE.value
        assert (_own(first)[0].admitted_entity_id
                == _own(second)[0].admitted_entity_id)

    def test_the_runtime_supplies_proposed_by_and_project_scope(self) -> None:
        applier = FakeApplier()
        _runtime(ScriptedModel({"researcher": [_draft()]}), applier=applier).run(
            "researcher", _one_tick())
        intent = applier.calls[0]
        assert intent.proposed_by == AgentProfile.RESEARCHER.value
        assert intent.project_id == "p1"

    def test_the_spine_refusal_is_recorded_as_data(self) -> None:
        applier = FakeApplier(refuse={"INSERT_TASK": "SCOPE_NOT_GOVERNED"})
        result = _runtime(ScriptedModel({"researcher": [_draft()]}),
                          applier=applier).run("researcher", _one_tick())
        proposal = _own(result)[0]
        assert proposal.admission == Admission.REFUSED.value
        assert PROPOSAL in result.refusal_codes()
        assert "SCOPE_NOT_GOVERNED" in proposal.admission_detail

    def test_an_oversized_draft_payload_refuses_and_preserves_the_body(self) -> None:
        artifacts = FakeArtifacts()
        payload = {"blob": "x" * (MAX_PAYLOAD_BYTES + 100)}
        result = _runtime(ScriptedModel({"researcher": [_draft(payload=payload)]}),
                          artifacts=artifacts).run("researcher", _one_tick())
        assert result.refusal_codes() == (RATIONALE,)
        assert artifacts.calls
        assert "preserved as" in result.refusals[0].detail

    def test_an_oversized_draft_payload_refuses_without_a_port(self) -> None:
        payload = {"blob": "x" * (MAX_PAYLOAD_BYTES + 100)}
        result = _runtime(ScriptedModel({"researcher": [_draft(payload=payload)]})
                          ).run("researcher", _one_tick())
        assert result.refusal_codes() == (RATIONALE,)
        assert "rather than truncated" in result.refusals[0].detail

    def test_a_model_overflow_is_preserved_and_never_parsed(self) -> None:
        from hermes.tools.models.router import ModelArtifactOverflow

        artifacts = FakeArtifacts()
        overflow = ModelArtifactOverflow(body=b"{}" * 40, size_bytes=80)
        result = _runtime(ScriptedModel({"researcher": [
            _proposal({}, overflow=overflow)]}), artifacts=artifacts).run(
            "researcher", _one_tick())
        assert result.refusal_codes() == (RATIONALE,)
        assert artifacts.stored
        assert result.proposals == ()


# ═══════════════════════ tools ═══════════════════════


class TestToolHandling:
    def _tool_proposal(self, capability_id: str = "source_search",
                       **overrides: Any) -> ModelProposal:
        structured: dict[str, Any] = {
            "kind": "INSERT_TASK", "rationale": "because", "payload": {},
            "tool_calls": [{"capability_id": capability_id,
                            "arguments": {"query": "momentum"}}],
        }
        structured.update(overrides)
        return _proposal(structured)

    def _runtime_and_trace(self, proposal: ModelProposal, **overrides: Any
                           ) -> tuple[AgentRuntime, ProposalSet, list[str]]:
        runtime = _runtime(ScriptedModel({"researcher": [proposal]}), **overrides)
        result = runtime.run("researcher", _one_tick())
        kinds = [event.kind for event in runtime.trace(result.run_id)]
        return runtime, result, kinds

    def test_a_declared_capability_runs_through_the_real_plane(self) -> None:
        executed: list[Any] = []
        invoker = _tool_capability_invoker(executed)
        _runtime, result, kinds = self._runtime_and_trace(
            self._tool_proposal(), capabilities=invoker,
            grants={"RESEARCHER": _research_grant()})
        assert executed == [{"query": "momentum"}]
        assert result.tool_calls == 1
        assert result.refusal_codes() == ()
        assert result.proposals[0].was_admitted()
        assert "TOOL_OBSERVED" in kinds
        assert "TOOL_FAILED" not in kinds

    def test_an_undeclared_capability_refuses_and_never_executes(self) -> None:
        executed: list[Any] = []
        invoker = _tool_capability_invoker(executed)
        _runtime, result, kinds = self._runtime_and_trace(
            self._tool_proposal("rm_rf"), capabilities=invoker)
        assert executed == []
        assert result.refusal_codes() == (ROLE,)
        assert "outside" in result.refusals[0].detail
        assert "TOOL_SKIPPED" in kinds

    def test_no_capability_port_refuses_the_call(self) -> None:
        _runtime, result, _kinds = self._runtime_and_trace(self._tool_proposal())
        assert result.refusal_codes() == (ROLE,)
        assert "no capability port" in result.refusals[0].detail

    def test_a_missing_grant_is_default_deny_at_the_plane(self) -> None:
        executed: list[Any] = []
        invoker = _tool_capability_invoker(executed)
        _runtime, result, _kinds = self._runtime_and_trace(
            self._tool_proposal(), capabilities=invoker, grants={})
        assert executed == []
        assert result.refusal_codes() == (ROLE,)

    def test_a_capability_refusal_is_recorded_with_its_provenance(self) -> None:
        refusal = CapabilityRefusal(code="EVIDENCE_REF", detail="no such artifact")
        _runtime, result, kinds = self._runtime_and_trace(
            self._tool_proposal(), capabilities=SpyCapabilities([refusal]))
        # A code outside this plane's set is mapped in, the original kept in detail.
        assert result.refusal_codes() == (MALFORMED_PAYLOAD,)
        assert "EVIDENCE_REF" in result.refusals[0].detail
        assert "TOOL_FAILED" in kinds

    def test_a_failed_observation_stops_the_run(self) -> None:
        _runtime, result, _kinds = self._runtime_and_trace(
            self._tool_proposal(),
            capabilities=SpyCapabilities([
                _failed_observation("source_search")]))
        assert result.refusal_codes() == (MALFORMED_PAYLOAD,)
        assert result.state == TaskStatus.FAILED.value
        assert result.termination == Termination.TOOL_FAILED.value
        assert result.tool_calls == 1

    def test_an_over_bound_tool_batch_refuses_whole(self) -> None:
        spy = SpyCapabilities()
        calls = [{"capability_id": "source_search", "arguments": {}}
                 for _ in range(9)]
        _runtime, result, _kinds = self._runtime_and_trace(
            self._tool_proposal(tool_calls=calls), capabilities=spy)
        assert spy.requests == []
        assert result.tool_calls == 0
        assert result.refusal_codes() == (MALFORMED_PAYLOAD,)

    def test_a_tool_call_with_unknown_keys_refuses(self) -> None:
        spy = SpyCapabilities()
        items = [{"capability_id": "source_search", "arguments": {}, "extra": 1}]
        _runtime, result, _kinds = self._runtime_and_trace(
            self._tool_proposal(tool_calls=items), capabilities=spy)
        assert spy.requests == []
        assert result.refusal_codes() == (MALFORMED_PAYLOAD,)

    def test_tool_arguments_must_be_a_mapping(self) -> None:
        spy = SpyCapabilities()
        items = [{"capability_id": "source_search", "arguments": "text"}]
        _runtime, result, _kinds = self._runtime_and_trace(
            self._tool_proposal(tool_calls=items), capabilities=spy)
        assert spy.requests == []
        assert result.refusal_codes() == (MALFORMED_PAYLOAD,)

    def test_the_derived_call_key_is_stable_across_runs(self) -> None:
        first = SpyCapabilities()
        second = SpyCapabilities()
        for spy in (first, second):
            _runtime(ScriptedModel({"researcher": [self._tool_proposal()]}),
                     capabilities=spy).run("researcher", _one_tick())
        assert (first.requests[0].idempotency_key
                == second.requests[0].idempotency_key)

    def test_the_observation_payload_never_becomes_a_proposal(self) -> None:
        applier = FakeApplier()
        _runtime, result, _kinds = self._runtime_and_trace(
            self._tool_proposal(), applier=applier,
            capabilities=SpyCapabilities())
        assert set(applier.kinds()) == {"INSERT_TASK"}
        assert len(_own(result)) == 1


# ═══════════════════════ delegation (B-2) ═══════════════════════


class TestDelegation:
    """Parent = `verifier`, child = `critic`: neither requires a review."""

    def _delegating(self, profile: str = "critic",
                    spec: Mapping[str, Any] | None = None,
                    **overrides: Any) -> ModelProposal:
        structured: dict[str, Any] = {
            "rationale": "delegate the check",
            "delegations": [{"profile": profile,
                             "spec": dict(spec or {"topic": "x"})}],
        }
        structured.update(overrides)
        return _proposal(structured)

    def _limits(self, **overrides: Any) -> RunLimits:
        fields: dict[str, Any] = {"max_ticks": 1}
        fields.update(overrides)
        return RunLimits(**fields)

    def test_a_delegation_is_a_child_task_with_a_derived_record(self) -> None:
        applier = FakeApplier()
        store = InMemoryDelegationStore()
        scripts = {"verifier": [self._delegating()],
                   "critic": [_draft("ABANDON", payload={"why": "weak"})]}
        model = ScriptedModel(scripts)
        runtime = _runtime(model, applier=applier, delegations=store)
        result = runtime.run("verifier", _ctx(limits=self._limits()))
        records = runtime.delegation_records(run_id=result.run_id)
        assert len(records) == 1
        record = records[0]
        assert record.state == DelegationState.DONE.value
        assert record.child_state == TaskStatus.SUCCEEDED.value
        assert record.child_digest
        assert record.child_run_id.startswith("run_")
        assert record.profile == "critic"
        assert record.agent_profile == AgentProfile.ADVERSARY.value
        assert record.lease_generation == "gen-1"
        assert record.child_intent_id
        assert applier.kinds() == ("INSERT_TASK", "ABANDON")
        assert "critic" in {request.profile for request in model.calls}

    def test_a_child_run_uses_the_child_profile_authority(self) -> None:
        applier = FakeApplier()
        scripts = {"verifier": [self._delegating()],
                   "critic": [_draft("BRANCH")]}
        runtime = _runtime(ScriptedModel(scripts), applier=applier)
        result = runtime.run("verifier", _ctx(limits=self._limits()))
        # BRANCH is outside critic's declared kinds: the child run refuses it, so
        # the only intent that ever reached the spine is the child's admission.
        assert applier.kinds() == ("INSERT_TASK",)
        record = runtime.delegation_records(run_id=result.run_id)[0]
        assert record.state == DelegationState.DONE.value

    def test_a_delegation_to_an_undeclared_profile_refuses(self) -> None:
        applier = FakeApplier()
        result = _runtime(ScriptedModel({"verifier": [self._delegating("ghost")]}),
                          applier=applier).run(
            "verifier", _ctx(limits=self._limits()))
        assert result.refusal_codes() == (ROLE,)
        assert applier.calls == []
        assert "not a declared profile" in result.refusals[0].detail

    def test_depth_beyond_the_declared_maximum_refuses(self) -> None:
        applier = FakeApplier()
        result = _runtime(ScriptedModel({"verifier": [self._delegating()]}),
                          applier=applier).run(
            "verifier",
            _ctx(depth=1, limits=self._limits(max_delegation_depth=1)))
        assert applier.calls == []
        assert result.refusal_codes() == (MALFORMED_PAYLOAD,)
        assert "delegation depth" in result.refusals[0].detail

    def test_child_runs_can_be_disabled_by_the_limits(self) -> None:
        result = _runtime(ScriptedModel({"verifier": [self._delegating()]})).run(
            "verifier", _ctx(limits=self._limits(allow_child_runs=False)))
        assert result.refusal_codes() == (MALFORMED_PAYLOAD,)
        assert "disabled" in result.refusals[0].detail

    def test_the_child_run_budget_is_enforced(self) -> None:
        applier = FakeApplier()
        items = [{"profile": "critic", "spec": {"i": i}} for i in range(3)]
        scripts = {"verifier": [self._delegating(delegations=items)],
                   "critic": [_draft("ABANDON"), _draft("ABANDON"),
                              _draft("ABANDON")]}
        result = _runtime(ScriptedModel(scripts), applier=applier).run(
            "verifier", _ctx(limits=self._limits(max_child_runs=1)))
        assert MALFORMED_PAYLOAD in result.refusal_codes()
        assert "budget" in " ".join(item.detail for item in result.refusals)

    def test_a_refused_child_admission_never_runs_the_child(self) -> None:
        applier = FakeApplier(refuse={"INSERT_TASK": "DEPENDENCY"})
        model = ScriptedModel({"verifier": [self._delegating()],
                               "critic": [_draft("ABANDON")]})
        runtime = _runtime(model, applier=applier,
                           delegations=InMemoryDelegationStore())
        result = runtime.run("verifier", _ctx(limits=self._limits()))
        record = runtime.delegation_records(run_id=result.run_id)[0]
        assert record.state == DelegationState.REFUSED.value
        assert "critic" not in {request.profile for request in model.calls}

    def test_an_oversized_delegated_spec_overflows_to_an_artifact_ref(self) -> None:
        artifacts = FakeArtifacts()
        big = {"blob": "x" * (MAX_PAYLOAD_BYTES + 200)}
        result = _runtime(ScriptedModel({"verifier": [self._delegating(spec=big)]}),
                          artifacts=artifacts).run(
            "verifier", _ctx(limits=self._limits()))
        assert artifacts.stored
        assert RATIONALE in result.refusal_codes()

    def test_an_oversized_delegated_spec_without_a_port_refuses(self) -> None:
        big = {"blob": "x" * (MAX_PAYLOAD_BYTES + 200)}
        result = _runtime(ScriptedModel({"verifier": [self._delegating(spec=big)]})
                          ).run("verifier", _ctx(limits=self._limits()))
        assert result.refusal_codes() == (RATIONALE,)
        assert "no artifact overflow port" in result.refusals[0].detail

    def test_completion_is_lease_generation_fenced(self) -> None:
        store = InMemoryDelegationStore()
        delegator = Delegator(store=store, profiles=load_profiles())
        record = delegator.plan(run_id="run_1", parent_task_id="t1",
                                project_id="p1", child_profile="critic",
                                lease_generation="gen-1", slot=0, spec={"a": 1},
                                intent_kind="INSERT_TASK")
        assert isinstance(record, DelegationRecord)
        foreign = delegator.complete(record, lease_generation="gen-2")
        assert isinstance(foreign, RuntimeRefusal)
        assert foreign.code == LOCK
        assert store.get(record.delegation_id).state == DelegationState.PENDING.value
        owned = delegator.complete(record, lease_generation="gen-1")
        assert isinstance(owned, DelegationRecord)
        assert owned.state == DelegationState.DONE.value

    def test_a_blank_generation_cannot_plan_or_complete(self) -> None:
        delegator = Delegator(store=InMemoryDelegationStore(),
                              profiles=load_profiles())
        planned = delegator.plan(run_id="run_1", parent_task_id="t1",
                                 project_id="p1", child_profile="critic",
                                 lease_generation="", slot=0, spec={},
                                 intent_kind="INSERT_TASK")
        assert isinstance(planned, RuntimeRefusal)
        assert planned.code == LOCK

    def test_pending_records_are_not_re_dispatched_after_a_restart(self) -> None:
        store = InMemoryDelegationStore()
        delegator = Delegator(store=store, profiles=load_profiles())
        record = delegator.plan(run_id="run_1", parent_task_id="t1",
                                project_id="p1", child_profile="critic",
                                lease_generation="gen-1", slot=0, spec={},
                                intent_kind="INSERT_TASK")
        assert isinstance(record, DelegationRecord)
        recovered = delegator.recover(run_id="run_1")
        assert [item.state for item in recovered] == [
            DelegationState.NO_SIGNAL.value]
        assert store.get(record.delegation_id).misses == 1
        assert delegator.recover(run_id="run_1") == ()

    def test_recovery_never_dispatches_by_construction(self) -> None:
        for kind in ("LIVE", "RESUMABLE", "NO_SIGNAL", "FAILED", "COMPLETE"):
            assert RecoveryVerdict(kind=kind, misses=0,
                                   reason="r").may_dispatch is False

    def test_pruning_keeps_pending_records(self) -> None:
        store = InMemoryDelegationStore()
        delegator = Delegator(store=store, profiles=load_profiles())
        done = delegator.plan(run_id="run_1", parent_task_id="t1", project_id="p1",
                              child_profile="critic", lease_generation="gen-1",
                              slot=0, spec={}, intent_kind="INSERT_TASK")
        pending = delegator.plan(run_id="run_1", parent_task_id="t1",
                                 project_id="p1", child_profile="critic",
                                 lease_generation="gen-1", slot=1, spec={},
                                 intent_kind="INSERT_TASK")
        assert isinstance(done, DelegationRecord)
        assert isinstance(pending, DelegationRecord)
        delegator.complete(done, lease_generation="gen-1")
        assert delegator.prune(run_id="run_1") == (done.delegation_id,)
        assert store.get(pending.delegation_id) is not None

    def test_pruning_honours_a_time_bound(self) -> None:
        clock = FakeClock()
        delegator = Delegator(store=InMemoryDelegationStore(),
                              profiles=load_profiles(), clock=clock)
        record = delegator.plan(run_id="run_1", parent_task_id="t1",
                                project_id="p1", child_profile="critic",
                                lease_generation="gen-1", slot=0, spec={},
                                intent_kind="INSERT_TASK")
        assert isinstance(record, DelegationRecord)
        delegator.complete(record, lease_generation="gen-1")
        clock.advance(60)
        assert delegator.prune(run_id="run_1", before=clock.stamp()) == (
            record.delegation_id,)

    def test_the_file_store_survives_a_restart(self, tmp_path: Path) -> None:
        first = Delegator(store=FileDelegationStore(tmp_path),
                          profiles=load_profiles())
        record = first.plan(run_id="run_1", parent_task_id="t1", project_id="p1",
                            child_profile="critic", lease_generation="gen-1",
                            slot=0, spec={"a": 1}, intent_kind="INSERT_TASK")
        assert isinstance(record, DelegationRecord)
        second = Delegator(store=FileDelegationStore(tmp_path),
                           profiles=load_profiles())
        assert second.records(run_id="run_1")[0].to_mapping() == record.to_mapping()
        assert second.recover(run_id="run_1")[0].state == (
            DelegationState.NO_SIGNAL.value)

    def test_a_corrupt_record_file_is_an_integrity_error(self,
                                                          tmp_path: Path) -> None:
        store = FileDelegationStore(tmp_path)
        path = store.path_for("del_broken")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{not json", encoding="utf-8")
        with pytest.raises(RuntimeFormatError):
            store.get("del_broken")

    def test_delegation_records_refuse_unknown_or_missing_keys(self) -> None:
        good = {
            "delegation_id": "del_1", "run_id": "run_1",
            "parent_task_id": "t1", "child_task_id": "t2", "project_id": "p1",
            "profile": "critic", "agent_profile": "ADVERSARY",
            "lease_generation": "gen-1",
        }
        with pytest.raises(RuntimeFormatError):
            DelegationRecord.from_mapping({**good, "extra": 1})
        with pytest.raises(RuntimeFormatError):
            DelegationRecord.from_mapping({"delegation_id": "del_1"})

    def test_child_commands_derive_every_identity_field(self) -> None:
        delegator = Delegator(store=InMemoryDelegationStore(),
                              profiles=load_profiles())
        record = delegator.plan(run_id="run_1", parent_task_id="t1",
                                project_id="p1", child_profile="critic",
                                lease_generation="gen-1", slot=0, spec={"a": 1},
                                intent_kind="INSERT_TASK")
        assert isinstance(record, DelegationRecord)
        command = delegator.child_command(record, spec={"a": 1}, slot=0)
        assert command["task_id"] == child_task_id_of("t1", "critic", 0)
        assert command["idempotency_key"] == child_idempotency_key_of(
            "t1", "critic", 0, {"a": 1})
        assert command["profile"] == AgentProfile.ADVERSARY.value

    def test_the_child_context_carries_the_depth_and_the_parent(self) -> None:
        delegator = Delegator(store=InMemoryDelegationStore(),
                              profiles=load_profiles())
        record = delegator.plan(run_id="run_1", parent_task_id="t1",
                                project_id="p1", child_profile="critic",
                                lease_generation="gen-1", slot=0, spec={},
                                intent_kind="INSERT_TASK")
        assert isinstance(record, DelegationRecord)
        child = delegator.child_context(record, depth=2,
                                        limits=RunLimits(max_child_runs=1))
        assert child.depth == 2
        assert child.parent_run_id == "run_1"
        assert child.parent_task_id == "t1"
        assert child.lease_generation == "gen-1"

    def test_review_is_a_child_run_of_the_declared_reviewer(self) -> None:
        applier = FakeApplier()
        scripts = {"researcher": [_draft("INSERT_TASK", payload={"x": 1})],
                   "critic": [_draft("REQUEST_HUMAN", payload={"why": "check"})]}
        model = ScriptedModel(scripts)
        runtime = _runtime(model, applier=applier)
        result = runtime.run("researcher", _one_tick())
        records = runtime.delegation_records(run_id=result.run_id)
        reviewers = [record for record in records if record.profile == "critic"]
        assert len(reviewers) == 1
        assert reviewers[0].state == DelegationState.DONE.value
        assert reviewers[0].payload_digest
        assert "critic" in {request.profile for request in model.calls}
        assert "DELEGATION_COMPLETED" in [
            event.kind for event in runtime.trace(result.run_id)]

    def test_a_child_run_never_reviews_its_own_reviewer(self) -> None:
        # planner's reviewer is verifier; a planner *child* (depth 1) must not
        # spawn that review, so no `verifier` delegation record ever appears.
        applier = FakeApplier()
        scripts = {"verifier": [self._delegating("planner", spec={"plan": "x"})],
                   "planner": [self._delegating()],
                   "critic": [_draft("ABANDON")]}
        runtime = _runtime(ScriptedModel(scripts), applier=applier,
                           delegations=InMemoryDelegationStore())
        result = runtime.run(
            "verifier", _ctx(limits=self._limits(max_delegation_depth=2)))
        profiles = [record.profile for record in runtime.delegation_records()]
        assert profiles == ["planner", "critic"]
        assert "verifier" not in profiles
        assert result.state == TaskStatus.SUCCEEDED.value

    def test_an_empty_proposal_set_is_not_reviewed(self) -> None:
        runtime = _runtime(ScriptedModel({"verifier": [_silent()]}))
        result = runtime.run("verifier", _ctx(limits=self._limits()))
        assert runtime.delegation_records(run_id=result.run_id) == ()


# ═══════════════════════ checkpoints + resume ═══════════════════════


class TestCheckpointsAndResume:
    def test_a_checkpoint_is_written_per_tick_and_at_the_end(self) -> None:
        model = ScriptedModel([_draft("ABANDON", rationale=f"r{i}")
                               for i in range(6)])
        runtime = _runtime(model)
        result = runtime.run("critic", _ctx())
        checkpoint = runtime.checkpoint(result.run_id)
        assert isinstance(checkpoint, Checkpoint)
        assert checkpoint.is_terminal()
        assert checkpoint.tick == result.ticks
        assert checkpoint.context_digest == _ctx().digest()
        assert len(checkpoint.proposals) == len(result.proposals) == result.ticks

    def test_an_opening_checkpoint_exists_before_the_first_tick(self) -> None:
        # A crash during tick 1 must still leave a record to classify.
        def explode(_request: Any) -> None:
            raise KeyboardInterrupt

        runtime = _runtime(ScriptedModel([_draft("ABANDON")], on_call=explode))
        with pytest.raises(KeyboardInterrupt):
            runtime.run("critic", _ctx())
        checkpoint = runtime.checkpoint(_run_id("critic"))
        assert isinstance(checkpoint, Checkpoint)
        assert checkpoint.tick == 0
        assert checkpoint.state == TaskStatus.RUNNING.value

    def test_every_checkpoint_carries_the_lease_generation(self) -> None:
        runtime = _runtime(ScriptedModel({"researcher": [_draft()]}))
        result = runtime.run("researcher", _one_tick(lease_generation="gen-7"))
        checkpoint = runtime.checkpoint(result.run_id)
        assert isinstance(checkpoint, Checkpoint)
        assert checkpoint.lease_generation == "gen-7"
        assert result.lease_generation == "gen-7"
        assert _own(result)[0].lease_generation == "gen-7"

    def test_resuming_a_terminal_run_is_a_no_op_read(self) -> None:
        applier = FakeApplier()
        model = ScriptedModel({"researcher": [_draft()]})
        runtime = _runtime(model, applier=applier)
        result = runtime.run("researcher", _one_tick())
        calls_after_run = model.call_count
        again = runtime.resume(result.run_id, lease_generation="gen-1")
        assert isinstance(again, ProposalSet)
        assert again.state == result.state
        assert again.digest() == result.digest()
        assert model.call_count == calls_after_run

    def test_resume_continues_at_the_next_tick_and_replays_the_prefix(self) -> None:
        applier = FakeApplier()
        store = InMemoryCheckpointStore()
        first_model = ScriptedModel([_draft("ABANDON", rationale=f"r{i}")
                                     for i in range(3)])
        first = _runtime(first_model, applier=applier, checkpoints=store).run(
            "critic", _ctx())
        terminal = store.get(first.run_id)
        assert isinstance(terminal, Checkpoint)
        # Forge the crash state: the run got through tick 1 and no further.
        store.put(terminal.with_changes(tick=1, state=TaskStatus.RUNNING.value,
                                        termination="",
                                        proposals=terminal.proposals[:1],
                                        refusals=(), delegations=()))
        tail_model = ScriptedModel([_draft("ABANDON", rationale="r1"),
                                    _draft("ABANDON", rationale="r2")])
        resumed_runtime = _runtime(tail_model, applier=applier, checkpoints=store)
        resumed = resumed_runtime.resume(first.run_id, lease_generation="gen-1")
        assert isinstance(resumed, ProposalSet)
        assert resumed.resumed_from_tick == 1
        assert resumed.ticks == first.ticks
        assert resumed.digest() == first.digest()
        assert resumed.proposals[0].admission == Admission.DUPLICATE.value
        assert resumed.proposals[0].admitted_entity_id == (
            first.proposals[0].admitted_entity_id)
        # Only the tail's ticks asked the model again.
        assert {request.profile for request in tail_model.calls} == {"critic"}

    def test_resume_refuses_a_changed_context_as_stale(self) -> None:
        store = InMemoryCheckpointStore()
        model = ScriptedModel([_draft("ABANDON", rationale=f"r{i}")
                               for i in range(3)])
        result = _runtime(model, checkpoints=store).run("critic", _ctx())
        terminal = store.get(result.run_id)
        assert isinstance(terminal, Checkpoint)
        store.put(terminal.with_changes(tick=1, state=TaskStatus.RUNNING.value,
                                        termination="", proposals=()))
        refusal = _runtime(ScriptedModel([]), checkpoints=store).resume(
            result.run_id, lease_generation="gen-1",
            context=_ctx(task_id="task-other"))
        assert isinstance(refusal, RuntimeRefusal)
        assert refusal.code == STALE

    def test_resume_under_a_foreign_generation_requires_takeover(self) -> None:
        store = InMemoryCheckpointStore()
        model = ScriptedModel([_draft("ABANDON", rationale=f"r{i}")
                               for i in range(3)])
        result = _runtime(model, checkpoints=store).run("critic", _ctx())
        terminal = store.get(result.run_id)
        assert isinstance(terminal, Checkpoint)
        store.put(terminal.with_changes(tick=1, state=TaskStatus.RUNNING.value,
                                        termination="", proposals=()))
        runtime = _runtime(ScriptedModel([_draft("ABANDON", rationale="r1")]),
                           checkpoints=store)
        refusal = runtime.resume(result.run_id, lease_generation="gen-2")
        assert isinstance(refusal, RuntimeRefusal)
        assert refusal.code == LOCK
        taken = runtime.resume(result.run_id, lease_generation="gen-2",
                               takeover=True)
        assert isinstance(taken, ProposalSet)
        assert taken.lease_generation == "gen-2"
        checkpoint = store.get(result.run_id)
        assert isinstance(checkpoint, Checkpoint)
        assert checkpoint.resumed_from_generation == "gen-1"

    def test_resume_of_an_unknown_run_refuses(self) -> None:
        refusal = _runtime(ScriptedModel([])).resume("run_missing",
                                                     lease_generation="gen-1")
        assert isinstance(refusal, RuntimeRefusal)
        assert refusal.code == MALFORMED_PAYLOAD

    def test_resume_without_a_generation_refuses(self) -> None:
        store = InMemoryCheckpointStore()
        model = ScriptedModel([_draft("ABANDON", rationale=f"r{i}")
                               for i in range(3)])
        result = _runtime(model, checkpoints=store).run("critic", _ctx())
        terminal = store.get(result.run_id)
        assert isinstance(terminal, Checkpoint)
        store.put(terminal.with_changes(tick=1, state=TaskStatus.RUNNING.value,
                                        termination="", lease_generation="",
                                        proposals=()))
        refusal = _runtime(ScriptedModel([]), checkpoints=store).resume(
            result.run_id)
        assert isinstance(refusal, RuntimeRefusal)
        assert refusal.code == LOCK

    def test_a_terminal_checkpoint_is_still_fenced_by_its_generation(self) -> None:
        store = InMemoryCheckpointStore()
        result = _runtime(ScriptedModel([_draft("ABANDON")]),
                          checkpoints=store).run("critic", _one_tick())
        terminal = store.get(result.run_id)
        assert isinstance(terminal, Checkpoint)
        assert terminal.is_terminal()
        # A terminal checkpoint is still *attributed*: a caller that is not the
        # lease it records may not read it (R4 probe 2e2).
        store.put(terminal.with_changes(lease_generation="gen-2"))
        runtime = _runtime(ScriptedModel([]), checkpoints=store)
        refusal = runtime.resume(result.run_id, lease_generation="gen-1")
        assert isinstance(refusal, RuntimeRefusal)
        assert refusal.code == LOCK
        assert "RESUME_REJECTED" in [event.kind
                                     for event in runtime.trace(result.run_id)]
        # The record's own generation reads it as the no-op it is.
        owned = runtime.resume(result.run_id, lease_generation="gen-2")
        assert isinstance(owned, ProposalSet)
        assert owned.digest() == result.digest()
        # …and an explicit takeover may adopt a foreign one.
        taken = runtime.resume(result.run_id, lease_generation="gen-3",
                               takeover=True)
        assert isinstance(taken, ProposalSet)
        assert taken.digest() == result.digest()

    def test_a_resume_never_adopts_the_recorded_generation_implicitly(self) -> None:
        store = InMemoryCheckpointStore()
        result = _runtime(ScriptedModel([_draft("ABANDON", rationale="r1")]),
                          checkpoints=store).run("critic", _ctx())
        terminal = store.get(result.run_id)
        assert isinstance(terminal, Checkpoint)
        # Forge a non-terminal record whose generation claims the run.
        store.put(terminal.with_changes(tick=1, state=TaskStatus.RUNNING.value,
                                        termination="", lease_generation="gen-9"))
        runtime = _runtime(ScriptedModel([_draft("ABANDON", rationale="r2")]),
                           checkpoints=store)
        refusal = runtime.resume(result.run_id)
        assert isinstance(refusal, RuntimeRefusal)
        assert refusal.code == LOCK
        # Takeover is the explicit act that may adopt the recorded generation.
        taken = runtime.resume(result.run_id, takeover=True)
        assert isinstance(taken, ProposalSet)
        assert taken.lease_generation == "gen-9"

    def test_a_resume_of_a_tampered_stored_context_refuses_stale(self) -> None:
        store = InMemoryCheckpointStore()
        result = _runtime(ScriptedModel([_draft("ABANDON", rationale="r1")]),
                          checkpoints=store).run("critic", _ctx())
        terminal = store.get(result.run_id)
        assert isinstance(terminal, Checkpoint)
        tampered = dict(terminal.context)
        tampered["payload"] = {"forged": True}
        store.put(terminal.with_changes(tick=1, state=TaskStatus.RUNNING.value,
                                        termination="", context=tampered))
        runtime = _runtime(ScriptedModel([]), checkpoints=store)
        # The stored context must prove itself against the digest it carries: a
        # record cannot hand the run a context it was not checkpointed on
        # (R4 probe 2c).
        refusal = runtime.resume(result.run_id, lease_generation="gen-1")
        assert isinstance(refusal, RuntimeRefusal)
        assert refusal.code == STALE
        # A caller-supplied context is verified the same way it always was.
        refusal = runtime.resume(result.run_id, lease_generation="gen-1",
                                 context=_ctx(payload={"forged": True}))
        assert isinstance(refusal, RuntimeRefusal)
        assert refusal.code == STALE

    def test_a_resume_refuses_a_checkpoint_that_denies_its_stored_id(
            self, tmp_path: Path) -> None:
        store = FileCheckpointStore(tmp_path)
        forged = Checkpoint(run_id="run_FORGED", profile="researcher",
                            agent_profile="RESEARCHER", task_id="task-root",
                            project_id="p1", lease_generation="gen-1", tick=2,
                            state=TaskStatus.SUCCEEDED.value,
                            termination=Termination.STOP_WHEN.value,
                            context=_ctx().to_mapping(),
                            context_digest=_ctx().digest())
        path = store.path_for("run_victim")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(forged.to_mapping()), encoding="utf-8")
        # The store's key is the record's identity: a body that disagrees with the
        # id it is filed under is not resumable (R4 probe 2g).
        refusal = _runtime(ScriptedModel([]), checkpoints=store).resume(
            "run_victim", lease_generation="gen-1")
        assert isinstance(refusal, RuntimeRefusal)
        assert refusal.code == MALFORMED_PAYLOAD
        # The disagreement is named: the operator sees what the file claimed.
        assert "run_FORGED" in refusal.detail

    def test_the_file_checkpoint_store_round_trips(self, tmp_path: Path) -> None:
        store = FileCheckpointStore(tmp_path)
        checkpoint = Checkpoint(run_id="run_1", profile="researcher",
                                agent_profile="RESEARCHER", task_id="t1",
                                project_id="p1", lease_generation="gen-1",
                                tick=2, state=TaskStatus.RUNNING.value,
                                context=_ctx().to_mapping(),
                                context_digest=_ctx().digest())
        store.put(checkpoint)
        reloaded = FileCheckpointStore(tmp_path).get("run_1")
        assert isinstance(reloaded, Checkpoint)
        assert reloaded.to_mapping() == checkpoint.to_mapping()

    def test_the_store_attributes_a_checkpoint_to_its_generation(
            self, tmp_path: Path) -> None:
        stores = [InMemoryCheckpointStore(), FileCheckpointStore(tmp_path)]
        for store in stores:
            store.put(Checkpoint(run_id="run_1", profile="researcher",
                                 agent_profile="RESEARCHER", task_id="t1",
                                 project_id="p1", lease_generation="gen-1"))
            assert store.owned("run_1", "gen-1") is not None
            assert store.owned("run_1", "gen-2") is None

    def test_a_corrupt_checkpoint_file_is_an_integrity_error(
            self, tmp_path: Path) -> None:
        store = FileCheckpointStore(tmp_path)
        store.path_for("run_1").parent.mkdir(parents=True, exist_ok=True)
        store.path_for("run_1").write_text("[1, 2]", encoding="utf-8")
        with pytest.raises(RuntimeFormatError):
            store.get("run_1")

    def test_checkpoint_mapping_refuses_unknown_and_missing_keys(self) -> None:
        good = {"run_id": "run_1", "profile": "researcher",
                "agent_profile": "RESEARCHER", "task_id": "t1",
                "project_id": "p1", "lease_generation": "gen-1"}
        with pytest.raises(RuntimeFormatError):
            Checkpoint.from_mapping({**good, "extra": 1})
        with pytest.raises(RuntimeFormatError):
            Checkpoint.from_mapping({"run_id": "run_1"})

    def test_a_proposal_mapping_round_trips(self) -> None:
        result = _runtime(ScriptedModel({"researcher": [_draft()]})).run(
            "researcher", _one_tick())
        proposal = _own(result)[0]
        assert Proposal.from_mapping(proposal.to_mapping()) == proposal

    def test_a_task_context_mapping_round_trips(self) -> None:
        context = _ctx(context=(_untrusted("hello"),), inputs=("artifact/1",),
                       payload={"a": 1})
        assert TaskContext.from_mapping(context.to_mapping()).digest() == (
            context.digest())

    def test_a_task_context_can_be_retargeted_onto_another_generation(self) -> None:
        retargeted = _ctx().with_changes(lease_generation="gen-2")
        assert retargeted.lease_generation == "gen-2"
        assert retargeted.digest() == _ctx().digest()  # the lease is excluded


# ═══════════════════════ crash recovery ═══════════════════════


class TestCrashRecovery:
    def _crash(self, store_dir: Path, script: Mapping[str, Any],
               profile: str = "critic") -> subprocess.CompletedProcess[str]:
        store_dir.mkdir(parents=True, exist_ok=True)
        script_path = store_dir.parent / "script.json"
        script_path.write_text(json.dumps(script), encoding="utf-8")
        return subprocess.run(
            [sys.executable, "-m", "tests.test_agent_runtime", "--crash-child",
             str(store_dir), str(script_path), profile],
            cwd=str(WORKTREE), capture_output=True, text=True, check=False,
            env={**os.environ,
                 "PYTHONPATH": f"{SRC_ROOT}{os.pathsep}{WORKTREE}"})

    def test_kill_9_mid_run_then_resume_reaches_the_same_terminal_state(
            self, tmp_path: Path) -> None:
        store_dir = tmp_path / "state"
        completed = self._crash(store_dir, {"critic": [
            _draft_mapping(kind="ABANDON", payload={"step": 1}), DIE]})
        assert completed.returncode == 9, completed.stderr

        checkpoint = FileCheckpointStore(store_dir).get(_run_id("critic"))
        assert isinstance(checkpoint, Checkpoint)
        assert checkpoint.tick == 1
        assert checkpoint.state == TaskStatus.RUNNING.value
        assert checkpoint.lease_generation == "gen-1"
        assert len(checkpoint.proposals) == 1

        # The uninterrupted run reaches NO_PROPOSALS at tick 3 with two drafts.
        uninterrupted = _runtime(ScriptedModel([
            _draft("ABANDON", payload={"step": 1}),
            _draft("ABANDON", payload={"step": 2}),
            _silent()])).run("critic", _ctx(limits=RunLimits(max_ticks=3)))
        assert uninterrupted.termination == Termination.NO_PROPOSALS.value
        assert uninterrupted.ticks == 3

        resumed_runtime = _runtime(
            ScriptedModel([_draft("ABANDON", payload={"step": 2}), _silent()]),
            checkpoints=FileCheckpointStore(store_dir))
        resumed = resumed_runtime.resume(_run_id("critic"),
                                        lease_generation="gen-1")
        assert isinstance(resumed, ProposalSet)
        assert resumed.state == uninterrupted.state
        assert resumed.termination == uninterrupted.termination
        assert resumed.ticks == uninterrupted.ticks
        assert resumed.resumed_from_tick == 1
        assert resumed.digest() == uninterrupted.digest()

    def test_kill_9_inside_the_review_child_resumes_to_the_same_terminal_set(
            self, tmp_path: Path) -> None:
        """A crash during the review child is a replay, not a no-op read.

        The review is the run's terminal act, so until it completes the parent's
        record must not be terminal-shaped. Before that rule the post-tick
        checkpoint claimed SUCCEEDED with only the parent's own proposal,
        `resume` returned it verbatim, and the resumed run reported a different
        terminal set than the uninterrupted one (R4 probe 1b).
        """
        store_dir = tmp_path / "state"
        completed = self._crash(store_dir, {
            "researcher": [_draft_mapping(payload={"step": 1})],
            "critic": [DIE]}, profile="researcher")
        assert completed.returncode == 9, completed.stderr

        store = FileCheckpointStore(store_dir)
        crashed = store.get(_run_id("researcher"))
        assert isinstance(crashed, Checkpoint)
        assert crashed.is_terminal() is False, (
            "a review was outstanding, so nothing terminal may be on record")
        assert crashed.tick == 0
        assert crashed.state == TaskStatus.RUNNING.value
        # F7: the review child's own checkpoint is the separate recovery unit,
        # filed under its derived run id.
        children = [run_id for run_id in store.run_ids()
                    if run_id != _run_id("researcher")]
        assert len(children) == 1
        child = store.get(children[0])
        assert isinstance(child, Checkpoint)
        assert child.profile == "critic"
        assert child.state == TaskStatus.RUNNING.value

        scripts = {"researcher": [_draft(payload={"step": 1})],
                   "critic": [_draft("ABANDON", payload={"why": "thin"})]}
        uninterrupted = _runtime(ScriptedModel(scripts)).run("researcher",
                                                             _one_tick())
        resumed_runtime = _runtime(
            ScriptedModel({"researcher": [_draft(payload={"step": 1})],
                           "critic": [_draft("ABANDON",
                                             payload={"why": "thin"})]}),
            checkpoints=FileCheckpointStore(store_dir))
        resumed = resumed_runtime.resume(_run_id("researcher"),
                                         lease_generation="gen-1")
        assert isinstance(resumed, ProposalSet)
        assert resumed.state == uninterrupted.state
        assert resumed.termination == uninterrupted.termination
        assert resumed.ticks == uninterrupted.ticks
        assert resumed.digest() == uninterrupted.digest()
        # F7: after the terminal act the parent's own checkpoint lists the review
        # child, so it is discoverable without globbing the store directory.
        terminal = FileCheckpointStore(store_dir).get(_run_id("researcher"))
        assert isinstance(terminal, Checkpoint)
        assert terminal.is_terminal()
        assert [record.profile for record in terminal.delegations] == ["critic"]
        assert terminal.delegations[0].state == DelegationState.DONE.value

    def test_a_crash_before_any_progress_classifies_no_signal(
            self, tmp_path: Path) -> None:
        store_dir = tmp_path / "state"
        completed = self._crash(store_dir, {"critic": [DIE]})
        assert completed.returncode == 9, completed.stderr
        checkpoint = FileCheckpointStore(store_dir).get(_run_id("critic"))
        assert isinstance(checkpoint, Checkpoint)
        assert checkpoint.tick == 0
        stale_clock = FakeClock()
        stale_clock.advance(3_600)
        runtime = _runtime(ScriptedModel({}),
                           checkpoints=FileCheckpointStore(store_dir),
                           clock=stale_clock)
        verdict, updated = runtime.recover(_run_id("critic"))
        assert verdict is not None
        assert updated is not None
        assert verdict.kind == types_module.RECOVERY_NO_SIGNAL
        assert verdict.misses == 1
        assert verdict.may_resume is False
        assert verdict.may_dispatch is False
        assert updated.state == TaskStatus.NO_SIGNAL.value

    def test_a_crash_after_progress_is_resumable_but_never_re_dispatched(
            self, tmp_path: Path) -> None:
        store_dir = tmp_path / "state"
        completed = self._crash(store_dir, {"critic": [
            _draft_mapping(kind="ABANDON", payload={"step": 1}), DIE]})
        assert completed.returncode == 9, completed.stderr
        stale_clock = FakeClock()
        stale_clock.advance(3_600)
        runtime = _runtime(ScriptedModel({}),
                           checkpoints=FileCheckpointStore(store_dir),
                           clock=stale_clock)
        verdict, updated = runtime.recover(_run_id("critic"))
        assert verdict is not None
        assert updated is not None
        assert verdict.kind == types_module.RECOVERY_RESUMABLE
        assert verdict.may_resume is True
        assert verdict.may_dispatch is False
        assert updated.state == TaskStatus.RUNNING.value

    def test_the_recovery_chain_running_no_signal_failed(self) -> None:
        checkpoint = Checkpoint(run_id="run_1", profile="researcher",
                                agent_profile="RESEARCHER", task_id="t1",
                                project_id="p1", lease_generation="gen-1",
                                tick=2, last_heartbeat=STAMP)
        first = classify_recovery(checkpoint, stale=True)
        assert first.kind == types_module.RECOVERY_RESUMABLE
        assert first.misses == 1
        assert first.may_resume is True
        assert first.may_dispatch is False
        after_first = apply_recovery(checkpoint, first, at=STAMP)
        second = classify_recovery(after_first, stale=True)
        assert second.kind == types_module.RECOVERY_FAILED
        assert second.misses == 2
        assert second.may_dispatch is False
        after_second = apply_recovery(after_first, second, at=STAMP)
        assert after_second.state == TaskStatus.FAILED.value
        third = classify_recovery(after_second, stale=True)
        assert third.kind == types_module.RECOVERY_COMPLETE
        assert MAX_MISSES == 2

    def test_a_fresh_heartbeat_is_left_alone(self) -> None:
        checkpoint = Checkpoint(run_id="run_1", profile="researcher",
                                agent_profile="RESEARCHER", task_id="t1",
                                project_id="p1", lease_generation="gen-1",
                                tick=2, last_heartbeat=STAMP)
        supervisor = Supervisor(clock=FakeClock(), heartbeat_horizon_seconds=60)
        verdict, updated = supervisor.recover(checkpoint)
        assert verdict.kind == types_module.RECOVERY_LIVE
        assert updated.state == TaskStatus.RUNNING.value
        assert updated.misses == 0

    def test_the_horizon_is_what_makes_a_heartbeat_stale(self) -> None:
        supervisor = Supervisor(clock=FakeClock(), heartbeat_horizon_seconds=60)
        assert supervisor.stale(STAMP) is False
        assert supervisor.stale("") is True
        assert supervisor.stale("not-a-timestamp") is True
        late = FakeClock()
        late.advance(120)
        assert supervisor.stale(STAMP, now=late.stamp()) is True

    def test_recovery_marks_pending_delegations_without_dispatching(self) -> None:
        store = InMemoryDelegationStore()
        delegator = Delegator(store=store, profiles=load_profiles())
        record = delegator.plan(run_id="run_1", parent_task_id="t1",
                                project_id="p1", child_profile="critic",
                                lease_generation="gen-1", slot=0, spec={},
                                intent_kind="INSERT_TASK")
        assert isinstance(record, DelegationRecord)
        checkpoints = InMemoryCheckpointStore()
        checkpoints.put(Checkpoint(
            run_id="run_1", profile="researcher", agent_profile="RESEARCHER",
            task_id="t1", project_id="p1", lease_generation="gen-1", tick=1,
            last_heartbeat=STAMP))
        runtime = _runtime(ScriptedModel({}), checkpoints=checkpoints,
                           delegations=store)
        verdict, _updated = runtime.recover("run_1")
        assert verdict is not None
        assert verdict.may_dispatch is False
        assert store.get(record.delegation_id).state == (
            DelegationState.NO_SIGNAL.value)
        assert "DELEGATION_NOT_RESTARTED" in [
            event.kind for event in runtime.trace("run_1")]

    def test_recovery_without_a_checkpoint_reports_nothing(self) -> None:
        assert _runtime(ScriptedModel({})).recover("run_missing") == (None, None)


def _draft_mapping(*, payload: Mapping[str, Any],
                   kind: str = "INSERT_TASK") -> dict[str, Any]:
    """A JSON-serializable model output for the crash-child's script file."""
    return {"kind": "proposal", "provider_id": "alpha", "model_id": "m1",
            "structured": {"kind": kind, "rationale": "because",
                           "payload": dict(payload)}}


def _run_id(profile: str) -> str:
    return run_id_of(profile, "task-root", "p1", 1)


def _entry_from_mapping(entry: Any) -> Any:
    if entry == DIE:
        return DIE
    if not isinstance(entry, dict):
        raise RuntimeFormatError(f"unreadable script entry: {entry!r}")
    if entry.get("kind") == "proposal":
        return _proposal(entry["structured"],
                         provider=str(entry.get("provider_id", "alpha")),
                         model=str(entry.get("model_id", "m1")))
    return _model_refusal(str(entry.get("code", MALFORMED_PAYLOAD)),
                          str(entry.get("detail", "")))


def _crash_child(argv: list[str]) -> int:
    """Crash-child mode: a real run in a real process that dies mid-run."""
    store_dir, script_path, profile = argv[0], argv[1], argv[2]
    raw = json.loads(Path(script_path).read_text(encoding="utf-8"))
    scripts = {name: [_entry_from_mapping(entry) for entry in entries]
               for name, entries in raw.items()}
    runtime = AgentRuntime(
        model=ScriptedModel(scripts),
        orchestration=FakeApplier(),
        profiles=load_profiles(),
        checkpoints=FileCheckpointStore(store_dir),
        clock=frozen_clock(STAMP))
    runtime.run(profile, TaskContext(task_id="task-root", project_id="p1",
                                     lease_generation="gen-1",
                                     limits=RunLimits(max_ticks=3)))
    return 0


# ═══════════════════════ supervision ═══════════════════════


class TestSupervision:
    def test_a_pre_cancelled_run_stops_before_any_call(self) -> None:
        token = RunCancelToken()
        token.cancel("operator withdrew")
        model = ScriptedModel([_draft("ABANDON")])
        result = _runtime(model).run("critic", _ctx(), token=token)
        assert result.state == TaskStatus.CANCELLED.value
        assert result.termination == Termination.CANCELLED.value
        assert model.call_count == 0
        assert result.ticks == 1

    def test_cancellation_between_ticks_is_honoured(self) -> None:
        token = RunCancelToken()
        model = ScriptedModel({"critic": [_draft("ABANDON", rationale="first"),
                                          _draft("ABANDON", rationale="second")]},
                              on_call=lambda _request: token.cancel())
        result = _runtime(model).run("critic", _ctx(), token=token)
        assert result.state == TaskStatus.CANCELLED.value
        assert result.termination == Termination.CANCELLED.value
        assert model.call_count == 1
        assert result.ticks == 2

    def test_a_cancel_during_the_review_child_stops_the_child_and_the_run(
            self) -> None:
        token = RunCancelToken()

        def cancel_on_review(request: Any) -> None:
            if request.profile == "critic":
                token.cancel("operator withdrew during the review")

        model = ScriptedModel({"researcher": [_draft(payload={"x": 1})],
                               "critic": [_draft("ABANDON", rationale="c1"),
                                          _draft("ABANDON", rationale="c2")]},
                              on_call=cancel_on_review)
        # Two ticks of budget so the child run has somewhere to *continue* to:
        # without the inherited token its second tick would call the model again.
        runtime = _runtime(model)
        result = runtime.run("researcher",
                             _ctx(limits=RunLimits(max_ticks=2)), token=token)
        # A cancel that lands while the review child runs is the run's terminal
        # state — never a silent SUCCEEDED (R4 probe 3a).
        assert token.cancelled is True
        assert result.state == TaskStatus.CANCELLED.value
        assert result.termination == Termination.CANCELLED.value
        # The child inherited the token: no model work starts after it is seen.
        assert model.calls_for("critic") == 1
        records = [record for record in runtime.delegation_records(
            run_id=result.run_id) if record.profile == "critic"]
        assert records[0].child_state == TaskStatus.CANCELLED.value
        checkpoint = runtime.checkpoint(result.run_id)
        assert isinstance(checkpoint, Checkpoint)
        assert checkpoint.state == TaskStatus.CANCELLED.value

    def test_a_cancel_inside_a_tool_call_stops_the_batch_and_the_run(self) -> None:
        token = RunCancelToken()
        requests: list[InvokeRequest] = []

        class CancellingPort:
            """A capability port that cancels the run from inside a call."""

            def invoke(self, request: InvokeRequest) -> Observation:
                requests.append(request)
                token.cancel("operator withdrew mid-batch")
                return _ok_observation(request.capability_id)

        batch = [{"capability_id": "source_search", "arguments": {"query": "a"}},
                 {"capability_id": "source_search", "arguments": {"query": "b"}}]
        model = ScriptedModel({"researcher": [
            _proposal({"kind": "EVIDENCE_TRANSITION", "rationale": "found it",
                       "payload": {"rung": 1}, "tool_calls": batch})]})
        result = _runtime(model, capabilities=CancellingPort()).run(
            "researcher", _one_tick(), token=token)
        # The batch stops at the cancel (no further call starts), and the tick
        # that would have reported STOP_WHEN records CANCELLED instead.
        assert len(requests) == 1
        assert model.calls_for("researcher") == 1
        assert result.state == TaskStatus.CANCELLED.value
        assert result.termination == Termination.CANCELLED.value
        assert result.ticks == 1
        # Honoured at the tick's teardown (the state records it there), not only
        # later at the terminal act: the run's own diagnostic says which.
        assert any("during the tick's work" in refusal.detail
                   for refusal in result.refusals)

    def test_an_expired_deadline_times_the_run_out(self) -> None:
        clock = FakeClock()

        def expire(_request: Any) -> None:
            clock.advance(10_000)

        model = ScriptedModel({"critic": [_draft("ABANDON", rationale="first")]},
                              on_call=expire)
        runtime = _runtime(model, clock=clock, monotonic=clock.monotonic)
        result = runtime.run("critic",
                             _ctx(limits=RunLimits(deadline_seconds=5)))
        assert result.termination == Termination.TIMEOUT.value
        assert result.state == TaskStatus.FAILED.value
        assert result.ticks == 2

    def test_the_token_satisfies_the_capability_planes_cancel_protocol(self) -> None:
        token = RunCancelToken()
        assert token.is_cancelled() is False
        token.cancel("stop")
        assert token.is_cancelled() is True
        assert token.reason == "stop"

    def test_streaming_events_reach_the_callback_in_order(self) -> None:
        seen: list[TraceEvent] = []
        runtime = _runtime(ScriptedModel({"researcher": [_draft()]}),
                           supervisor=Supervisor(clock=FakeClock(),
                                                 on_event=seen.append))
        result = runtime.run("researcher", _one_tick())
        assert [event for event in seen
                if event.run_id == result.run_id] == list(
            runtime.trace(result.run_id))
        assert [event.sequence for event in runtime.trace(result.run_id)] == list(
            range(1, len(runtime.trace(result.run_id)) + 1))


# ═══════════════════════ concurrency ═══════════════════════


class TestConcurrentAgentsUnderOneLease:
    def test_two_runs_share_one_lease_generation_without_interference(self) -> None:
        applier = FakeApplier()
        checkpoints = InMemoryCheckpointStore()
        delegations = InMemoryDelegationStore()
        results: dict[str, ProposalSet] = {}
        errors: list[BaseException] = []

        def worker(profile: str, task_id: str, script: list[Any]) -> None:
            try:
                runtime = _runtime(ScriptedModel({profile: script}),
                                   applier=applier, checkpoints=checkpoints,
                                   delegations=delegations)
                results[profile] = runtime.run(
                    profile, _one_tick(task_id=task_id,
                                       lease_generation="gen-shared"))
            except BaseException as exc:  # noqa: BLE001 — surfaced below
                errors.append(exc)

        threads = [
            threading.Thread(target=worker,
                             args=("verifier", "task-a",
                                   [_draft("EVIDENCE_TRANSITION",
                                           payload={"who": "a"})])),
            threading.Thread(target=worker,
                             args=("critic", "task-b",
                                   [_draft("ABANDON", payload={"who": "b"})])),
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        assert errors == []
        assert sorted(results) == ["critic", "verifier"]
        for result in results.values():
            assert result.state == TaskStatus.SUCCEEDED.value
            assert result.lease_generation == "gen-shared"
            assert result.proposals
            assert all(proposal.lease_generation == "gen-shared"
                       for proposal in result.proposals)
        run_ids = {result.run_id for result in results.values()}
        assert len(run_ids) == 2
        assert set(checkpoints.run_ids()) == run_ids
        assert all(intent.proposed_by == AgentProfile.ADVERSARY.value
                   for intent in applier.calls)
        assert len(applier.calls) == 2

    def test_two_writers_of_one_run_id_neither_collide_nor_tear(
            self, tmp_path: Path) -> None:
        """Same-run concurrency has a defined outcome: last complete write wins.

        The supported shape is two *disjoint* runs under one lease (above). Two
        writers on one run id are a configuration error against the store's
        documented single-writer precondition, and the store's job is to make that
        error benign: a unique temporary file per write plus an atomic replace, so
        no writer crashes and no reader ever sees a torn document (R4 probe 4a).
        """
        store = FileCheckpointStore(tmp_path)
        errors: list[BaseException] = []
        written: list[str] = []
        guard = threading.Lock()

        def writer(tag: str) -> None:
            try:
                for tick in range(1, 21):
                    checkpoint = Checkpoint(
                        run_id="run_SAME", profile="verifier",
                        agent_profile="ADVERSARY", task_id=f"t-{tag}",
                        project_id="p1", lease_generation="gen-shared", tick=tick,
                        state=TaskStatus.RUNNING.value,
                        context=_ctx().to_mapping(),
                        context_digest=_ctx().digest(), tool_calls=tick)
                    store.put(checkpoint)
                    with guard:
                        written.append(json.dumps(checkpoint.to_mapping(),
                                                  sort_keys=True, indent=2,
                                                  ensure_ascii=False))
            except BaseException as exc:  # noqa: BLE001 — surfaced below
                errors.append(exc)

        threads = [threading.Thread(target=writer, args=(tag,))
                   for tag in ("a", "b")]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        assert errors == []
        assert len(written) == 40
        # The document is one writer's whole checkpoint, never a mix of two.
        final = store.path_for("run_SAME").read_text(encoding="utf-8")
        assert final in written
        reloaded = store.get("run_SAME")
        assert isinstance(reloaded, Checkpoint)
        assert reloaded.task_id in {"t-a", "t-b"}
        assert reloaded.tick == reloaded.tool_calls
        # No temporary file is ever visible as a document.
        assert [path.name for path in tmp_path.glob("*.json")] == ["run_SAME.json"]


# ═══════════════════════ trace + projection (B-5) ═══════════════════════


class TestTraceAndProjection:
    def test_the_trace_records_the_run_and_is_ordered(self) -> None:
        runtime = _runtime(ScriptedModel({"researcher": [_draft()]}))
        result = runtime.run("researcher", _one_tick())
        events = runtime.trace(result.run_id)
        kinds = [event.kind for event in events]
        assert kinds[0] == "RUN_STARTED"
        assert "MODEL_REQUESTED" in kinds
        assert "INTENT_ADMITTED" in kinds
        # The terminal checkpoint is written *after* the termination event, so it
        # is the last thing the trace shows.
        assert kinds[-2] == "RUN_TERMINATED"
        assert kinds[-1] == "CHECKPOINT_WRITTEN"
        assert [event.sequence for event in events] == list(
            range(1, len(events) + 1))
        assert all(event.lease_generation == "gen-1" for event in events)
        assert all(event.kind in TRACE_KINDS for event in events)

    def test_projection_orders_by_declared_dependency(self) -> None:
        events = (
            TraceEvent(sequence=1, kind="MODEL_REQUESTED", run_id="r", tick=1,
                       lease_generation="g", at=STAMP),
            TraceEvent(sequence=2, kind="TICK_STARTED", run_id="r", tick=1,
                       lease_generation="g", at=STAMP),
        )
        ordered, kind_order, _unsatisfied, cycles = order_events(events)
        assert kind_order == ("TICK_STARTED", "MODEL_REQUESTED")
        assert [event.sequence for event in ordered] == [2, 1]
        assert cycles == ()

    def test_projection_reports_absent_dependencies_and_unknowns(self) -> None:
        events = (
            TraceEvent(sequence=1, kind="MODEL_REQUESTED", run_id="r", tick=1,
                       lease_generation="g", at=STAMP),
            TraceEvent(sequence=2, kind="NOT_A_KIND", run_id="r", tick=1,
                       lease_generation="g", at=STAMP),
        )
        projected = project_trace(events)
        # An absent dependency is *unsatisfied*; a kind this plane does not
        # declare is *unknown*. Both are reported, neither is invented.
        assert "MODEL_REQUESTED" in projected.unsatisfied
        assert projected.unknown == ("NOT_A_KIND",)
        assert "NOT_A_KIND" not in projected.unsatisfied
        assert projected.digest

    def test_projection_reports_a_cycle_instead_of_guessing(
            self, monkeypatch: pytest.MonkeyPatch) -> None:
        patched = dict(HANDLER_DEPENDENCIES)
        patched["TICK_STARTED"] = ("RUN_TERMINATED",)
        patched["RUN_TERMINATED"] = ("TICK_STARTED",)
        monkeypatch.setattr(projection_module, "HANDLER_DEPENDENCIES", patched)
        events = (
            TraceEvent(sequence=1, kind="TICK_STARTED", run_id="r", tick=1,
                       lease_generation="g", at=STAMP),
            TraceEvent(sequence=2, kind="RUN_TERMINATED", run_id="r", tick=1,
                       lease_generation="g", at=STAMP),
        )
        projected = project_trace(events)
        assert set(projected.cycles) == {"TICK_STARTED", "RUN_TERMINATED"}
        assert projected.sequence_is_monotonic()
        assert projections_are_immutable()

    def test_every_trace_kind_declares_its_dependencies(self) -> None:
        assert set(HANDLER_DEPENDENCIES) == set(TRACE_KINDS)

    def test_projection_is_pure_and_idempotent(self) -> None:
        runtime = _runtime(ScriptedModel({"researcher": [_draft()]}))
        result = runtime.run("researcher", _one_tick())
        events = runtime.trace(result.run_id)
        before = tuple(events)
        first = project_trace(events)
        second = project_trace(events)
        assert events == before
        assert first.digest == second.digest
        assert first.counts == second.counts
        assert first.events_for("INTENT_ADMITTED")
        assert json.dumps(run_summary(events))
        assert events_by_tick(events)[1]

    def test_the_projection_module_is_mechanically_pure(self) -> None:
        source = _module_source(projection_module)
        tree = ast.parse(source)
        banned_calls = {"open", "execute", "executemany", "commit", "rollback",
                        "write_text", "write_bytes", "unlink", "connect",
                        "_append_event_to_db"}
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                func = node.func
                name = (func.attr if isinstance(func, ast.Attribute)
                        else getattr(func, "id", ""))
                assert name not in banned_calls, name
        allowed = {"__future__", "collections.abc", "dataclasses", "types", "typing",
                   "hermes.agents.runtime.types"}
        imports = {node.module for node in ast.walk(tree)
                   if isinstance(node, ast.ImportFrom) and node.module}
        imports |= {alias.name for node in ast.walk(tree)
                    if isinstance(node, ast.Import) for alias in node.names}
        assert imports <= allowed, imports
        referenced = _referenced_names(source)
        assert "conn" not in referenced
        assert "execute" not in referenced
        assert "_append_event_to_db" not in source
        assert "repositories" not in source
        assert "hermes.persistence" not in source

    def test_projection_holds_no_mutable_module_state(self) -> None:
        mutable = {name: value for name, value in vars(projection_module).items()
                   if isinstance(value, (dict, list, set))
                   and not name.startswith("__")}
        assert mutable == {}


def projections_are_immutable() -> bool:
    """The declared dependency map is read-only (a projection cannot mutate it)."""
    with pytest.raises(TypeError):
        HANDLER_DEPENDENCIES["RUN_STARTED"] = ("TICK_STARTED",)  # type: ignore[index]
    return True


# ═══════════════════════ real spine integration ═══════════════════════


@pytest.fixture
def spine() -> Any:
    conn = connect(":memory:")
    migrate_to_latest(conn)
    ProjectRepository(conn).create("p1", "Test")
    yield conn
    conn.close()


def _spine_applier(conn: Any) -> Any:
    clock = frozen_clock(STAMP)
    return lambda intent: apply_intent(conn, intent, clock=clock)


class TestRealSpineIntegration:
    """The runtime against the real `apply_intent` — no fake verdicts.

    A review-free profile is used so the mutation counts are the *parent run's*
    alone (the review child is covered in `TestDelegation`).
    """

    def _solo(self, tmp_path: Path) -> ProfileSpec:
        return _temp_profile(tmp_path, "solo", _base_document_yaml())

    def test_an_admitted_proposal_lands_and_a_re_emit_is_a_duplicate(
            self, spine: Any, tmp_path: Path) -> None:
        spec = self._solo(tmp_path)
        applier = _spine_applier(spine)
        runtime = _runtime(
            ScriptedModel({"solo": [_draft(payload={"spec": {"q": "x"}})]}),
            applier=applier, profiles={"solo": spec})
        first = runtime.run("solo", _one_tick())
        assert first.proposals[0].admission == Admission.ADMITTED.value
        task_id = first.proposals[0].admitted_entity_id
        assert len(spine.execute("SELECT task_id FROM tasks WHERE task_id = ?",
                                 (task_id,)).fetchall()) == 1

        second = _runtime(
            ScriptedModel({"solo": [_draft(payload={"spec": {"q": "x"}})]}),
            applier=applier, profiles={"solo": spec}).run("solo", _one_tick())
        assert second.proposals[0].admission == Admission.DUPLICATE.value
        assert second.proposals[0].admitted_entity_id == task_id
        assert spine.execute("SELECT COUNT(*) FROM tasks").fetchone()[0] == 1

    def test_an_unwired_kind_surfaces_the_spine_refusal_as_data(
            self, spine: Any) -> None:
        applier = _spine_applier(spine)
        # planner may propose BRANCH, but the gateway has no validator wired for
        # it in this phase: the plane records the refusal, it does not work
        # around it.
        runtime = _runtime(ScriptedModel({"planner": [_draft("BRANCH",
                                                             payload={})]}),
                           applier=applier)
        result = runtime.run("planner", _one_tick())
        assert result.proposals[0].admission == Admission.REFUSED.value
        assert result.refusal_codes() == (PROPOSAL,)
        # The gateway's own words, verbatim: the refusal is surfaced, not replaced.
        assert "not wired" in result.proposals[0].admission_detail

    def test_a_run_against_the_real_spine_makes_exactly_one_mutation(
            self, spine: Any, tmp_path: Path) -> None:
        spec = self._solo(tmp_path)
        applier = _spine_applier(spine)
        runtime = _runtime(ScriptedModel({"solo": [_draft()]}), applier=applier,
                           profiles={"solo": spec})
        runtime.run("solo", _one_tick())
        applied = spine.execute(
            "SELECT COUNT(*) FROM events WHERE event_type = 'IntentApplied'"
        ).fetchone()[0]
        assert applied == 1


# ═══════════════════════ real model plane integration ═══════════════════════


def _model_profile(*, supports_tool_calls: bool = True) -> ModelProfile:
    return ModelProfile(
        provider_id="alpha", model_id="m1", context_window_tokens=8000,
        max_output_tokens=1024, supports_structured_output=True,
        supports_tool_calls=supports_tool_calls,
        tiers=("research", "experiment", "adversary", "synthesis", "planning"))


def _response(text: str) -> ModelResponse:
    return ModelResponse(text=text, usage=TokenUsage(10, 5))


def _router(responses: list[str], *,
            proposable: frozenset[str] | None = None) -> ModelRouter:
    """The *real* router over a scripted live provider (no scripted model port)."""
    profile = _model_profile()
    clock = FakeClock()
    return ModelRouter(
        providers=[LiveProvider([_response(text) for text in responses],
                                (profile,))],
        policy=ModelPlanePolicy(
            tier_refs=dict.fromkeys(profile.tiers, "alpha:m1"),
            retry_policy=RetryPolicy(max_retries=0, base_delay_seconds=0.0,
                                     max_delay_seconds=0.0, jitter=False)),
        clock=clock,
        proposable_kinds=(proposable if proposable is not None else frozenset(
            kind.value for kind in IntentKind.llm_proposable())),
        tool_allowlist=frozenset(load_profiles()["researcher"].tools),
        sleep=clock.sleep,
        jitter_source=lambda low, high: 0.0)


class TestRealModelPlaneIntegration:
    """The runtime driving the real router, against a review-free profile."""

    def _solo(self, tmp_path: Path) -> dict[str, ProfileSpec]:
        return {"solo": _temp_profile(tmp_path, "solo", _base_document_yaml())}

    def test_the_runtime_drives_the_real_router_end_to_end(
            self, tmp_path: Path) -> None:
        router = _router([json.dumps({"kind": "INSERT_TASK",
                                      "rationale": "because",
                                      "payload": {"spec": {"q": "x"}}})])
        applier = FakeApplier()
        result = _runtime(router, applier=applier,
                          profiles=self._solo(tmp_path)).run("solo", _one_tick())
        assert result.proposals[0].was_admitted()
        assert result.proposals[0].model == "alpha:m1"
        assert router.provider_attempts == 1
        assert len(router.accounting()) == 1
        router.verify_accounting()

    def test_the_plane_refuses_a_decision_shaped_output(
            self, tmp_path: Path) -> None:
        router = _router([json.dumps({"kind": "INSERT_TASK",
                                      "rationale": "because",
                                      "payload": {},
                                      "verdict": "SUPPORTED"})])
        applier = FakeApplier()
        result = _runtime(router, applier=applier,
                          profiles=self._solo(tmp_path)).run("solo", _one_tick())
        assert result.proposals == ()
        assert result.refusal_codes() == (PROPOSAL,)
        assert result.termination == Termination.MODEL_REFUSED.value
        assert applier.calls == []

    def test_the_plane_refuses_a_kind_outside_the_proposable_set(
            self, tmp_path: Path) -> None:
        router = _router([json.dumps({"kind": "ADMIT_TASK", "rationale": "because",
                                      "payload": {}})],
                         proposable=frozenset({"INSERT_TASK"}))
        result = _runtime(router, profiles=self._solo(tmp_path)).run(
            "solo", _one_tick())
        # The model plane refuses the internal-only kind before this plane sees it.
        assert result.refusal_codes() == (ROLE,)
        assert result.proposals == ()


if __name__ == "__main__":  # pragma: no cover — the crash-child entry point
    if len(sys.argv) > 3 and sys.argv[1] == "--crash-child":
        raise SystemExit(_crash_child(sys.argv[2:]))
    raise SystemExit(0)
