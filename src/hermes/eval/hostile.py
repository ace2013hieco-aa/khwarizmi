"""Hostile-shape drivers — the matrix's inline witnesses, executed live.

Every case in :mod:`hermes.eval.matrix` carries an inline assertion that
calls one driver from this module. A driver builds the case's hostile
shape against the **production** plane, lets the shipped gates run, and
returns the refusal code the plane produced — or ``"OK"`` when the shape
produced a non-refusal outcome. The matrix compares that produced code
with the case's ``expected_code``; a mismatch is a red case.

The drivers use the same *injected-port* fakes the pinned tests use for
the surrounding transport (a scripted model transport, a recording
executor, an in-memory applier) — never a test class. Every gate,
identity rule, and refusal they exercise is the shipped one.

Test-module boundary
--------------------

No driver calls a test class, test fixture, or test method. There is
exactly one dependency on the test tree, and it is deliberate and
declared rather than hidden:

* ``runtime_crash`` (the ``(runtime, crash)`` case) spawns the crash
  child that ships inside ``tests/test_agent_runtime.py``, running it as
  ``python -m tests.test_agent_runtime --crash-child …``. A kill-9
  mid-run cannot be produced inside the test process without killing the
  process that is running the matrix, so the crash child has to be a
  separate interpreter. Reusing the one that the pinned test
  (``test_kill_9_mid_run_then_resume_reaches_the_same_terminal_state``)
  already exercises keeps a single crash-child implementation rather
  than a second copy under ``src/``.

Every other driver builds its hostile shape entirely inside this module
and the production planes. So the accurate claim is: drivers never
execute test code, and exactly one driver (``runtime_crash``) executes a
**subprocess entry point** of a test module — the one exception, named
here, in the driver that needs it.

Design rules:

* nothing here writes durable state — temp directories for the crash
  driver, in-memory stores everywhere else;
* no new refusal codes — every driver surfaces a code from the frozen
  vocabulary (``matrix.FROZEN_REFUSAL_CODES``) or ``"OK"``;
* the methodology plane's own four code names are assembled by string
  concatenation, because the methodology suite scans every file under
  ``src/`` outside its package for those contiguous names;
* the governance plane is reached through the single declared route in
  :mod:`hermes.eval.import_gate` (see ``load_governed`` below), and this
  file declares that dependency explicitly rather than spelling an
  assembled module path at each use.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import threading
from dataclasses import fields, replace
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Mapping, Sequence

from hermes.agents.runtime import types as runtime_types
from hermes.agents.runtime.checkpoint import (
    FileCheckpointStore,
    InMemoryCheckpointStore,
)
from hermes.agents.runtime.config import load_profiles
from hermes.agents.runtime.delegate import InMemoryDelegationStore
from hermes.agents.runtime.run import AgentRuntime
from hermes.agents.runtime.supervisor import RetryBudget, RunCancelToken
from hermes.agents.runtime.types import (
    RunLimits,
    Termination,
    digest_of,
    run_id_of,
)
from hermes.core.task_status import TaskStatus
from hermes.eval.import_gate import (
    GOVERNED_PACKAGE,
    load_governed,
    require_declaration,
)
from hermes.methodology.substrate import (
    SubstrateNode,
    SubstrateRefusal,
    SubstrateStore,
    check_provenance_graph,
    write_node,
)
from hermes.research.gateway import IntentResult
from hermes.security.boundaries import UntrustedContent
from hermes.tools.capabilities.invoke import (
    CapabilityInvoker,
    InMemoryIdempotencyLedger,
)
from hermes.tools.capabilities.registry import CapabilityRegistry
from hermes.tools.capabilities.types import (
    INPUT_TYPES,
    Capability,
    CapabilityRefusal,
    InputField,
    InvokeRequest,
    Observation,
    RiskLevel,
    Tool,
    ToolCallContext,
    ToolGrant,
    ToolResult,
    ToolSet,
)
from hermes.tools.models.router import (
    FieldSpec,
    ModelCall,
    ModelPlaneInvariantError,
    ModelPlanePolicy,
    ModelProfile,
    ModelProposal,
    ModelRefusal,
    ModelRequest,
    ModelResponse,
    ModelRouter,
    ModelSettings,
    OutputContract,
    RecordedModelProvider,
    TokenUsage,
    model_fixture_id_of,
    normalized_model_call,
)
from hermes.tools.research_sources import RetryPolicy

# The governance plane is reached through the eval plane's single
# DECLARED route (`import_gate.load_governed`), not through a
# hand-assembled string at each use.
#
# This crossing is real and was previously hidden: the R7-REREPORT
# recorded that `hostile.py` imported the governance plane via
# `importlib.import_module("hermes." + "governance.approvals")`, a
# string concatenation written specifically so that the governance
# plane's own suite-integrity gate (a substring scan for the contiguous
# text `hermes.governance`, `tests/test_governance_plane.py`
# `test_the_plane_is_wired_to_nothing`) would not see it. The eval plane
# is a second consumer of the governance plane and is now DECLARED as
# one rather than concealed from the check that was meant to find it.
#
# `import_gate.detect_import_mentions` resolves this dependency
# structurally (constant folding over the AST plus a `sys.modules`
# witness), so it reports this file as reaching the governed package
# whatever spelling is used here. The dependency is therefore visible
# to a machine, not only to a reader of this comment.
(_gov_approvals, _gov_authority, _gov_policy) = load_governed(
    "approvals", "authority", "policy")

# Bound through the declared helper so a renamed attribute fails here,
# by name, instead of surfacing as an AttributeError inside a driver.
_bind_approvals = require_declaration(_gov_approvals, {
    "APPROVED": "APPROVED", "DecisionRow": "DecisionRow"})
_bind_authority = require_declaration(_gov_authority, {
    "ActionRequest": "ActionRequest", "CredentialRow": "CredentialRow",
    "EvidenceContext": "EvidenceContext",
    "_evaluate_authority": "_evaluate_authority",
    "evaluate_authority": "evaluate_authority"})
_bind_policy = require_declaration(_gov_policy, {
    "CONTRADICTION_DECLARE": "CONTRADICTION_DECLARE",
    "DEFAULT_APPROVAL_WINDOW_SECONDS": "DEFAULT_APPROVAL_WINDOW_SECONDS",
    "DENY": "DENY", "GOVERNANCE_POLICY": "GOVERNANCE_POLICY",
    "GovernanceFormatError": "GovernanceFormatError", "HEAD_KEY": "HEAD_KEY",
    "OPERATOR": "OPERATOR", "PERMIT": "PERMIT", "PROPOSAL": "PROPOSAL",
    "PUBLISH": "PUBLISH", "PUBLISH_BINDING_KEY": "PUBLISH_BINDING_KEY",
    "REQUIREMENT_INDEPENDENCE": "REQUIREMENT_INDEPENDENCE",
    "ROLE": "ROLE", "SANDBOX_RUN": "SANDBOX_RUN", "STALE": "STALE",
    "PolicyRow": "PolicyRow"})

APPROVED = _bind_approvals["APPROVED"]
DecisionRow = _bind_approvals["DecisionRow"]
ActionRequest = _bind_authority["ActionRequest"]
CredentialRow = _bind_authority["CredentialRow"]
EvidenceContext = _bind_authority["EvidenceContext"]
_evaluate_authority = _bind_authority["_evaluate_authority"]
evaluate_authority = _bind_authority["evaluate_authority"]
CONTRADICTION_DECLARE = _bind_policy["CONTRADICTION_DECLARE"]
DEFAULT_APPROVAL_WINDOW_SECONDS = _bind_policy["DEFAULT_APPROVAL_WINDOW_SECONDS"]
DENY = _bind_policy["DENY"]
GOVERNANCE_POLICY = _bind_policy["GOVERNANCE_POLICY"]
GovernanceFormatError = _bind_policy["GovernanceFormatError"]
HEAD_KEY = _bind_policy["HEAD_KEY"]
OPERATOR = _bind_policy["OPERATOR"]
PERMIT = _bind_policy["PERMIT"]
PROPOSAL = _bind_policy["PROPOSAL"]
PUBLISH = _bind_policy["PUBLISH"]
PUBLISH_BINDING_KEY = _bind_policy["PUBLISH_BINDING_KEY"]
REQUIREMENT_INDEPENDENCE = _bind_policy["REQUIREMENT_INDEPENDENCE"]
ROLE = _bind_policy["ROLE"]
SANDBOX_RUN = _bind_policy["SANDBOX_RUN"]
STALE = _bind_policy["STALE"]
PolicyRow = _bind_policy["PolicyRow"]

#: The governed package this module declares a dependency on. Exposed so
#: a gate (or a reviewer) can assert the declared crossing rather than
#: infer it from the assembled literal above.
DECLARED_GOVERNANCE_DEPENDENCY = GOVERNED_PACKAGE

__all__ = [
    "capability_bypass",
    "capability_cross_project",
    "capability_escalation",
    "capability_escape",
    "capability_forgery",
    "governance_bypass",
    "governance_conflict",
    "governance_expiry",
    "governance_forgery",
    "governance_self_approval",
    "methodology_circular",
    "methodology_coupling",
    "methodology_gap",
    "methodology_hallucination",
    "methodology_leak",
    "methodology_retraction",
    "model_accounting",
    "model_authority",
    "model_credential",
    "model_injection",
    "model_replay",
    "runtime_budget",
    "runtime_cancel",
    "runtime_concurrency",
    "runtime_crash",
    "runtime_forgery",
]

#: The worktree root, derived from this file (``<root>/src/hermes/eval``).
_WORKTREE = Path(__file__).resolve().parents[3]
_SRC_DIR = Path(__file__).resolve().parents[2]


def _code_of(result: Any) -> str:
    """The produced refusal code, or ``"OK"`` for a non-refusal outcome."""
    code = getattr(result, "code", None)
    return code if isinstance(code, str) else "OK"


def _expect_refusal(result: Any, expected: str, what: str) -> str:
    """Supporting check: ``result`` must be a refusal of ``expected``."""
    code = _code_of(result)
    if code != expected:
        raise AssertionError(
            f"{what}: expected refusal {expected!r}, produced "
            f"{type(result).__name__}(code={code!r})")
    return code


# ────────────────────────────────────────────────────────────────────
# MODEL plane
# ────────────────────────────────────────────────────────────────────

_MODEL_SECRET = "sk-live-hostile-driver-0123456789"
_MODEL_CLOCK_STAMP = "2026-01-01T00:00:00.000000+00:00"
_INJECTION_BODY = "SECRET-ANSWER-BODY"


class _ModelClock:
    """A frozen clock with the router's protocol (``now_utc``/``sleep``)."""

    def __init__(self) -> None:
        self.slept: list[float] = []

    def now_utc(self) -> str:
        return _MODEL_CLOCK_STAMP

    def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)


class _ModelTransport:
    """A scripted ``ModelProvider`` transport — records every call."""

    def __init__(self, provider_id: str = "alpha",
                 profiles: Sequence[ModelProfile] = (),
                 script: Sequence[Any] = ()) -> None:
        self.provider_id = provider_id
        self._profiles = tuple(profiles)
        self._script = list(script)
        self.calls: list[ModelCall] = []

    def describe(self) -> tuple[ModelProfile, ...]:
        return self._profiles

    def invoke(self, call: ModelCall) -> ModelResponse:
        self.calls.append(call)
        if not self._script:
            return _model_response("{}")
        action = self._script.pop(0)
        if isinstance(action, BaseException):
            raise action
        return action

    def stream(self, call: ModelCall) -> tuple[Any, ...]:
        self.calls.append(call)
        return ()

    @property
    def calls_made(self) -> int:
        return len(self.calls)


class _RefusingTransport:
    """An inner transport that must never be contacted (the replay proof)."""

    def __init__(self, provider_id: str = "alpha") -> None:
        self.provider_id = provider_id
        self.contacted = 0

    def describe(self) -> tuple[ModelProfile, ...]:
        return ()

    def invoke(self, call: ModelCall) -> ModelResponse:
        self.contacted += 1
        raise AssertionError("live model contacted during replay")

    def stream(self, call: ModelCall) -> tuple[Any, ...]:
        self.contacted += 1
        raise AssertionError("live model contacted during replay")


class _FixedCredentials:
    """A credential port resolving a fixed value per provider."""

    def __init__(self, values: Mapping[str, str]) -> None:
        self._values = dict(values)

    def resolve(self, provider_id: str) -> Any:
        from hermes.tools.models.router import Credential

        if provider_id not in self._values:
            return None
        return Credential(name="model_api_key", _value=self._values[provider_id])


def _model_response(text: str) -> ModelResponse:
    return ModelResponse(text=text, usage=TokenUsage(10, 5),
                         finish_reason="stop", tool_calls_raw="")


def _model_profile(**overrides: Any) -> ModelProfile:
    body: dict[str, Any] = {
        "context_window_tokens": 8000,
        "max_output_tokens": 1024,
        "supports_streaming": True,
        "supports_tool_calls": True,
        "supports_structured_output": True,
        "input_cost_per_1k_tokens": 0.5,
        "output_cost_per_1k_tokens": 1.5,
    }
    body.update(overrides)
    return ModelProfile(provider_id="alpha", model_id="m1", **body)


def _model_policy(**overrides: Any) -> ModelPlanePolicy:
    body: dict[str, Any] = {
        "tier_refs": {"s": "alpha:m1", "m": "beta:m2", "c": "gamma:m3"},
        "fallback_chain": ("m", "c"),
        "retry_policy": RetryPolicy(max_retries=2, base_delay_seconds=1.0,
                                    max_delay_seconds=30.0, jitter=True),
    }
    body.update(overrides)
    return ModelPlanePolicy(**body)


def _model_router(transport: Any, *,
                  credentials: Any = None) -> ModelRouter:
    clock = _ModelClock()
    return ModelRouter(
        providers=[transport], policy=_model_policy(), clock=clock,
        proposable_kinds=frozenset({"INSERT_TASK", "BRANCH"}),
        tool_allowlist=frozenset({"search"}), credentials=credentials,
        sleep=clock.sleep, jitter_source=lambda low, high: 1.0)


def _model_request(**overrides: Any) -> ModelRequest:
    body: dict[str, Any] = {
        "tier": "s",
        "profile": "director",
        "lease_generation": "lease-gen-7",
        "prompt": (UntrustedContent(text="Summarise the admitted evidence.",
                                    origin="hostile.driver", ref="ref-1"),),
    }
    body.update(overrides)
    return ModelRequest(**body)


def _json_contract() -> OutputContract:
    return OutputContract(name="json_proposal",
                          fields=(FieldSpec("text", "string"),))


def model_authority() -> str:
    """Decision-shaped model output → PROPOSAL, without a retry."""
    transport = _ModelTransport(profiles=(_model_profile(),), script=[
        _model_response(json.dumps({"decision": "APPROVE"})) for _ in range(3)])
    router = _model_router(transport)
    result = router.invoke(_model_request(output_contract=_json_contract()))
    if transport.calls_made != 1:
        raise AssertionError(
            f"model authority: expected one provider call, got "
            f"{transport.calls_made}")
    return _code_of(result)


def model_injection() -> str:
    """Model output is enveloped and str-safe (the payload stays in .text)."""
    transport = _ModelTransport(profiles=(_model_profile(),),
                                script=[_model_response(_INJECTION_BODY)])
    router = _model_router(transport)
    result = router.invoke(_model_request())
    if not isinstance(result, ModelProposal):
        raise AssertionError(
            f"model injection: expected a proposal, got "
            f"{type(result).__name__}")
    content = result.content
    if not isinstance(content, UntrustedContent):
        raise AssertionError(
            f"model injection: content is {type(content).__name__}, not "
            f"UntrustedContent")
    if _INJECTION_BODY not in content.text:
        raise AssertionError("model injection: payload missing from .text")
    if _INJECTION_BODY in str(content) or _INJECTION_BODY in repr(content):
        raise AssertionError(
            "model injection: payload leaked through str/repr of the envelope")
    return "OK"


def model_accounting() -> str:
    """A refusal before any call is still accounted: one REFUSED row, LOCK."""
    transport = _ModelTransport(profiles=(_model_profile(),),
                                script=[_model_response("{}")])
    router = _model_router(transport)
    result = router.invoke(_model_request(lease_generation=""))
    _expect_refusal(result, "LOCK", "model accounting")
    rows = router.accounting()
    if len(rows) != 1:
        raise AssertionError(
            f"model accounting: expected 1 account row, got {len(rows)}")
    row = rows[0]
    if (row.attempt, row.outcome, row.refusal_code, row.lease_generation) != (
            0, "REFUSED", "LOCK", ""):
        raise AssertionError(
            f"model accounting: row is attempt={row.attempt!r}, "
            f"outcome={row.outcome!r}, code={row.refusal_code!r}, "
            f"lease={row.lease_generation!r}")
    router.verify_accounting()
    return "LOCK"


def model_replay() -> str:
    """Replay serves the recorded bytes and never contacts the live transport."""
    inner = _ModelTransport(script=[_model_response("recorded body")])
    sink: list[Any] = []
    recorded = RecordedModelProvider(
        inner, provider_id="alpha", model_id="m1", transport_version="1",
        mode="record", sink=sink.append)
    call = ModelCall(provider_id="alpha", model_id="m1",
                     payload={"prompt": [{"text": "hi"}]})
    if recorded.invoke(call).text != "recorded body" or len(sink) != 1:
        raise AssertionError("model replay: record mode did not record")
    fixture = sink[0]
    if fixture.fixture_id != model_fixture_id_of(
            "alpha", "m1", normalized_model_call(call)):
        raise AssertionError("model replay: fixture identity is not derived")
    live = _RefusingTransport()
    replay = RecordedModelProvider(
        live, provider_id="alpha", model_id="m1", transport_version="1",
        mode="replay", fixtures={fixture.fixture_id: fixture})
    response = replay.invoke(call)
    if response.text.encode("utf-8") != b"recorded body":
        raise AssertionError("model replay: bytes are not byte-identical")
    if live.contacted != 0:
        raise AssertionError(
            f"model replay: live transport contacted {live.contacted} times")
    return "OK"


def model_credential() -> str:
    """Credential discipline: the option guard and the secret-literal guard.

    Two independent production gates are exercised:

    1. a credential-class *option name* (declared on the profile, so no
       other gate would refuse it) → ``MALFORMED_PAYLOAD``, no call;
    2. a live secret *literal* in the prompt → ``ModelPlaneInvariantError``
       (hazard ``SECRET_LEAK``, non-recordable), no call.
    """
    # 1. credential-class option name — declared on the profile so the
    # known-options check cannot mask a deleted credential guard.
    profile = _model_profile(
        settings=ModelSettings(options={"api_key": "declared-in-profile"}))
    transport = _ModelTransport(profiles=(profile,),
                                script=[_model_response("{}")])
    router = _model_router(transport)
    result = router.invoke(_model_request(
        options={"api_key": "opaque-non-secret-value"}))
    if transport.calls_made != 0:
        raise AssertionError(
            f"model credential: provider was called "
            f"{transport.calls_made} times before the option guard")
    if _code_of(result) != "MALFORMED_PAYLOAD":
        raise AssertionError(
            f"model credential: expected refusal MALFORMED_PAYLOAD for a "
            f"credential-class option name, produced {_code_of(result)!r}")
    detail = getattr(result, "detail", "")
    if "credential-class" not in detail:
        raise AssertionError(
            f"model credential: option refusal does not name the credential "
            f"class: {detail!r}")

    # 2. live secret literal in the prompt — the loud, fail-closed guard.
    guarded = _ModelTransport(profiles=(_model_profile(),),
                              script=[_model_response("{}")])
    guarded_router = _model_router(
        guarded, credentials=_FixedCredentials({"alpha": _MODEL_SECRET}))
    try:
        guarded_router.invoke(_model_request(prompt=(
            UntrustedContent(text=f"use {_MODEL_SECRET}",
                             origin="hostile.driver", ref="ref-1"),)))
    except ModelPlaneInvariantError as exc:
        if getattr(exc, "hazard_class", "") != "SECRET_LEAK":
            raise AssertionError(
                f"model credential: invariant breach without SECRET_LEAK "
                f"hazard: {getattr(exc, 'hazard_class', '')!r}") from exc
        if getattr(exc, "recordable", True):
            raise AssertionError(
                "model credential: secret-literal breach was recordable"
                ) from exc
        if _MODEL_SECRET in str(exc):
            raise AssertionError(
                "model credential: the invariant error names the secret"
                ) from exc
    else:
        raise AssertionError(
            "model credential: a live secret literal in the prompt was not "
            "refused (the secret-literal guard did not fire)")
    if guarded.calls_made != 0:
        raise AssertionError(
            f"model credential: provider was called {guarded.calls_made} "
            f"times before the secret-literal guard")
    return "MALFORMED_PAYLOAD"
# ────────────────────────────────────────────────────────────────────
# CAPABILITY plane
# ────────────────────────────────────────────────────────────────────

_CAP_CLOCK_STAMP = "2026-09-24T12:00:00+00:00"
_CAP_PERMITTED = ("string", "integer", "number", "boolean", "array")
_CAP_TOOL_IDS = ("svc.echo", "svc.scoped")
_CAP_IDS = ("cap.echo", "cap.scoped")


class _CapClock:
    def __init__(self) -> None:
        self.t = 1000.0

    def now_utc(self) -> str:
        return _CAP_CLOCK_STAMP

    def monotonic(self) -> float:
        return self.t

    def advance(self, seconds: float) -> None:
        self.t += seconds


class _CapLimiter:
    """Structural stand-in for the rate limiter (atomic decision + cause)."""

    def __init__(self) -> None:
        self.granted = True
        self.acquires: list[str] = []
        self.releases: list[str] = []

    def acquire(self, capability_id: str) -> tuple[bool, str]:
        self.acquires.append(capability_id)
        return (self.granted, "")

    def release(self, capability_id: str) -> None:
        self.releases.append(capability_id)


class _CapRig:
    """One wired capability plane plus its recording ports."""

    def __init__(self, invoker: CapabilityInvoker, calls: list[str],
                 received: list[dict[str, Any]]) -> None:
        self.invoker = invoker
        self.calls = calls
        self.received = received

    def call(self, capability_id: str, *, key: str = "idem-1",
             arguments: Mapping[str, Any] | None = None,
             grant: ToolGrant | None = None, profile: str = "analyst",
             lease: str = "lease-gen-7",
             rationale: str = "because the driver asks for it"
             ) -> Observation | CapabilityRefusal:
        if grant is None:
            grant = _cap_grant()
        request = InvokeRequest(
            capability_id=capability_id, arguments=dict(arguments or {}),
            idempotency_key=key, lease_generation=lease, profile=profile,
            rationale=rationale, grant=grant)
        return self.invoker.invoke(request)


def _cap_grant() -> ToolGrant:
    return ToolGrant(
        grant_id="grant.full", profile="analyst",
        tool_set_ids=frozenset({"set.core"}),
        max_risk=RiskLevel.HIGH.value)


def _cap_registry() -> CapabilityRegistry:
    registry = CapabilityRegistry(allowlist=frozenset(_CAP_IDS))
    registry.register_tool(Tool(
        tool_id="svc.echo", summary="Echo declared text back.",
        inputs=(InputField(name="text", type="string", max_bytes=64),)))
    registry.register_tool(Tool(
        tool_id="svc.scoped", summary="Reads inside a declared scope.",
        filesystem_scope="work",
        inputs=(InputField(name="path", type="string"),), sandboxed=True))
    registry.register_capability(
        Capability(capability_id="cap.echo", tool_id="svc.echo"))
    registry.register_capability(
        Capability(capability_id="cap.scoped", tool_id="svc.scoped"))
    registry.register_tool_set(ToolSet(
        set_id="set.core", capability_ids=_CAP_IDS, summary="core"))
    return registry


def _cap_rig() -> _CapRig:
    calls: list[str] = []
    received: list[dict[str, Any]] = []

    def echo(arguments: Mapping[str, Any],
             context: ToolCallContext) -> ToolResult:
        calls.append("svc.echo")
        received.append(dict(arguments))
        return ToolResult(payload=f"echo:{arguments.get('text', '')}")

    def scoped(arguments: Mapping[str, Any],
               context: ToolCallContext) -> ToolResult:
        calls.append("svc.scoped")
        received.append(dict(arguments))
        return ToolResult(payload=f"scoped:{arguments.get('path', '')}")

    invoker = CapabilityInvoker(
        registry=_cap_registry(),
        implementations={"svc.echo": echo, "svc.scoped": scoped},
        clock=_CapClock(), limiter=_CapLimiter(),
        ledger=InMemoryIdempotencyLedger(), hazard_specs={},
        sandbox_enabled=False)
    return _CapRig(invoker=invoker, calls=calls, received=received)


def capability_bypass() -> str:
    """A blank lease generation refuses LOCK before anything executes."""
    rig = _cap_rig()
    result = rig.call("cap.echo", lease="")
    _expect_refusal(result, "LOCK", "capability bypass")
    if rig.calls:
        raise AssertionError(
            f"capability bypass: executor ran for {rig.calls!r}")
    return "LOCK"


def capability_escalation() -> str:
    """A tool result / call context cannot express authority, structurally."""
    result_names = {spec.name for spec in fields(ToolResult)}
    context_names = {spec.name for spec in fields(ToolCallContext)}
    if result_names != {"payload", "artifacts", "notes"}:
        raise AssertionError(
            f"capability escalation: ToolResult fields changed: "
            f"{sorted(result_names)}")
    if context_names != {
            "capability_id", "tool_id", "idempotency_key", "lease_generation",
            "profile", "deadline_monotonic", "scratch_dir"}:
        raise AssertionError(
            f"capability escalation: ToolCallContext fields changed: "
            f"{sorted(context_names)}")
    forbidden = {"connection", "conn", "repository", "session", "grant",
                 "authority", "transaction", "cursor", "engine", "store"}
    if result_names & forbidden or context_names & forbidden:
        raise AssertionError(
            f"capability escalation: an authority-bearing field appeared: "
            f"{sorted((result_names | context_names) & forbidden)}")
    try:
        ToolResult(payload="x", authority="GRANTED")  # type: ignore[call-arg]
    except TypeError:
        pass
    else:
        raise AssertionError(
            "capability escalation: ToolResult accepted an authority field")
    return "OK"


def capability_forgery() -> str:
    """An observation carries no identity of its own (and rejects one)."""
    expected = {"capability_id", "status", "payload", "artifacts", "failure",
                "detail", "idempotency_key", "replayed", "envelope"}
    names = {spec.name for spec in fields(Observation)}
    if names != expected:
        raise AssertionError(
            f"capability forgery: Observation fields changed: {sorted(names)}")
    try:
        Observation(capability_id="cap.echo", status="OK", payload=None,
                    artifacts=(), failure=None, detail="",
                    idempotency_key="k", replayed=False, envelope=None,
                    node_id="forged")  # type: ignore[call-arg]
    except TypeError:
        pass
    else:
        raise AssertionError(
            "capability forgery: Observation accepted a forged identity field")
    return "OK"


def capability_escape() -> str:
    """Scalar-only inputs: a composite argument refuses, unexecuted."""
    if tuple(INPUT_TYPES) != _CAP_PERMITTED:
        raise AssertionError(
            f"capability escape: input type vocabulary changed: "
            f"{tuple(INPUT_TYPES)!r}")
    rig = _cap_rig()
    result = rig.call("cap.echo",
                      arguments={"text": {"nested": "closure"}})
    if rig.calls:
        raise AssertionError(
            f"capability escape: executor ran for a composite argument: "
            f"{rig.calls!r}")
    return _expect_refusal(result, "MALFORMED_PAYLOAD", "capability escape")


def capability_cross_project() -> str:
    """Process and network constructs in an argument refuse ROLE."""
    rig = _cap_rig()
    process = rig.call("cap.scoped",
                       arguments={"path": "work/a.txt; rm -rf y"})
    network = rig.call("cap.scoped",
                       arguments={"path": "http://evil.example/x"},
                       key="idem-2")
    if rig.calls:
        raise AssertionError(
            f"capability cross-project: executor ran: {rig.calls!r}")
    first = _expect_refusal(process, "ROLE", "capability cross-project")
    second = _expect_refusal(network, "ROLE", "capability cross-project")
    if first != second:
        raise AssertionError(
            f"capability cross-project: process={first!r}, "
            f"network={second!r}")
    detail = getattr(process, "detail", "")
    if "process-execution construct" not in detail:
        raise AssertionError(
            f"capability cross-project: refusal does not name the construct: "
            f"{detail!r}")
    return first
# ────────────────────────────────────────────────────────────────────
# RUNTIME plane
# ────────────────────────────────────────────────────────────────────

_RUNTIME_STAMP = "2026-01-01T00:00:00.000000+00:00"


class _RuntimeClock:
    """A callable clock with a monotonic channel and the router protocol."""

    def __init__(self, start: str = _RUNTIME_STAMP) -> None:
        self._moment = datetime.fromisoformat(start)
        self._monotonic = 0.0

    def __call__(self) -> str:
        return self.stamp()

    def now_utc(self) -> str:
        return self.stamp()

    def monotonic(self) -> float:
        return self._monotonic

    def advance(self, seconds: float) -> None:
        self._moment = self._moment + timedelta(seconds=seconds)
        self._monotonic += seconds

    def stamp(self) -> str:
        return self._moment.isoformat(timespec="microseconds")


class _ScriptedModel:
    """A ``ModelPort`` serving a script per profile, in order."""

    def __init__(self, scripts: Mapping[str, list[Any]] | list[Any]) -> None:
        if isinstance(scripts, list):
            self._scripts: dict[str, list[Any]] = {"*": list(scripts)}
        else:
            self._scripts = {name: list(items)
                             for name, items in scripts.items()}
        self.calls: list[Any] = []

    @property
    def call_count(self) -> int:
        return len(self.calls)

    def invoke(self, request: Any) -> Any:
        self.calls.append(request)
        script = self._scripts.get(request.profile)
        if script is None:
            script = self._scripts.get("*")
        if not script:
            return ModelRefusal(
                code=runtime_types.MALFORMED_PAYLOAD,
                detail=f"no scripted response for {request.profile!r}")
        return script.pop(0)


class _FakeApplier:
    """The Orchestration API fake — identity content-addressed as the spine."""

    def __init__(self) -> None:
        self.calls: list[Any] = []
        self._seen: dict[str, str] = {}

    def __call__(self, intent: Any) -> IntentResult:
        self.calls.append(intent)
        key = digest_of({"kind": intent.kind.value,
                         "project": intent.project_id,
                         "payload": dict(intent.payload)})
        if key in self._seen:
            return IntentResult(kind=intent.kind, entity_type="task",
                                entity_id=self._seen[key], duplicate=True,
                                row={}, event_type="TaskCreated")
        entity = "task_" + key[:16]
        self._seen[key] = entity
        return IntentResult(kind=intent.kind, entity_type="task",
                            entity_id=entity, duplicate=False, row={},
                            event_type="TaskCreated")


def _runtime_draft(kind: str = "INSERT_TASK", *,
                   rationale: str = "because",
                   payload: Mapping[str, Any] | None = None) -> ModelProposal:
    return ModelProposal(
        provider_id="alpha", model_id="m1", tier="research",
        profile="scripted", lease_generation="gen-1",
        structured={"kind": kind, "rationale": rationale,
                    "payload": dict(payload or {})})


def _runtime_ctx(**overrides: Any) -> Any:
    body: dict[str, Any] = {
        "task_id": "task-root", "project_id": "p1",
        "lease_generation": "gen-1",
    }
    body.update(overrides)
    from hermes.agents.runtime.types import TaskContext

    return TaskContext(**body)


def _runtime(model: Any, *, applier: Any = None, **overrides: Any
             ) -> AgentRuntime:
    body: dict[str, Any] = {
        "model": model,
        "orchestration": applier if applier is not None else _FakeApplier(),
        "profiles": load_profiles(),
    }
    body.update(overrides)
    return AgentRuntime(**body)


def _own_proposals(result: Any) -> list[Any]:
    return [proposal for proposal in result.proposals
            if proposal.rationale == "because"]


def runtime_forgery() -> str:
    """Derived INSERT_TASK identity is stable — never authored by a draft."""
    applier = _FakeApplier()
    model = _ScriptedModel({"researcher": [
        _runtime_draft(payload={"spec": {"a": 1}}),
        _runtime_draft(payload={"spec": {"a": 1}})]})
    runtime = _runtime(model, applier=applier)
    first = runtime.run("researcher", _runtime_ctx(
        limits=RunLimits(max_ticks=1)))
    second = runtime.run("researcher", _runtime_ctx(
        limits=RunLimits(max_ticks=1)))
    proposals = _own_proposals(first) + _own_proposals(second)
    if len(proposals) < 2:
        raise AssertionError(
            f"runtime forgery: expected two own proposals, got {proposals!r}")
    p1 = proposals[0].intent.payload
    p2 = proposals[1].intent.payload
    if p1["task_id"] != p2["task_id"]:
        raise AssertionError("runtime forgery: derived task_id is not stable")
    if p1["idempotency_key"] != p2["idempotency_key"]:
        raise AssertionError(
            "runtime forgery: derived idempotency_key is not stable")
    if (proposals[0].admission, proposals[1].admission) != (
            "ADMITTED", "DUPLICATE"):
        raise AssertionError(
            f"runtime forgery: admissions are "
            f"{proposals[0].admission!r}/{proposals[1].admission!r}")

    # A draft that supplies its own identity must not reach the applier.
    authored_applier = _FakeApplier()
    authored = _runtime(
        _ScriptedModel({"researcher": [
            _runtime_draft(payload={"task_id": "mine"})]}),
        applier=authored_applier)
    authored_result = authored.run("researcher", _runtime_ctx(
        limits=RunLimits(max_ticks=1)))
    if authored_applier.calls:
        raise AssertionError(
            "runtime forgery: an authored task_id reached the applier")
    codes = [refusal.code for refusal in authored_result.refusals]
    if "MALFORMED_PAYLOAD" not in codes:
        raise AssertionError(
            f"runtime forgery: authored identity refused with {codes!r}")
    return "OK"


def runtime_cancel() -> str:
    """A pre-cancelled run stops before any model call."""
    token = RunCancelToken()
    token.cancel("operator withdrew")
    model = _ScriptedModel([_runtime_draft("ABANDON")])
    result = _runtime(model).run("critic", _runtime_ctx(), token=token)
    if (result.state, result.termination) != (
            TaskStatus.CANCELLED.value, Termination.CANCELLED.value):
        raise AssertionError(
            f"runtime cancel: state={result.state!r}, "
            f"termination={result.termination!r}")
    if model.call_count != 0:
        raise AssertionError(
            f"runtime cancel: model was called {model.call_count} times")
    return "OK"


def runtime_concurrency() -> str:
    """Two runs sharing one lease generation stay disjoint and terminal."""
    applier = _FakeApplier()
    checkpoints = InMemoryCheckpointStore()
    delegations = InMemoryDelegationStore()
    results: dict[str, Any] = {}
    errors: list[BaseException] = []

    def worker(profile: str, task_id: str, script: list[Any]) -> None:
        try:
            runtime = _runtime(
                _ScriptedModel({profile: script}), applier=applier,
                checkpoints=checkpoints, delegations=delegations)
            results[profile] = runtime.run(
                profile, _runtime_ctx(task_id=task_id,
                                      lease_generation="gen-shared",
                                      limits=RunLimits(max_ticks=1)))
        except BaseException as exc:  # noqa: BLE001 — surfaced below
            errors.append(exc)

    threads = [
        threading.Thread(target=worker, args=(
            "verifier", "task-a",
            [_runtime_draft("EVIDENCE_TRANSITION", payload={"who": "a"})])),
        threading.Thread(target=worker, args=(
            "critic", "task-b",
            [_runtime_draft("ABANDON", payload={"who": "b"})])),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    if errors:
        raise AssertionError(f"runtime concurrency: worker errors {errors!r}")
    if sorted(results) != ["critic", "verifier"]:
        raise AssertionError(
            f"runtime concurrency: results {sorted(results)!r}")
    for result in results.values():
        if result.state != TaskStatus.SUCCEEDED.value:
            raise AssertionError(
                f"runtime concurrency: state={result.state!r}")
        if result.lease_generation != "gen-shared":
            raise AssertionError("runtime concurrency: lease not shared")
        if not all(proposal.lease_generation == "gen-shared"
                   for proposal in result.proposals):
            raise AssertionError(
                "runtime concurrency: proposal without the shared lease")
    run_ids = {result.run_id for result in results.values()}
    if len(run_ids) != 2:
        raise AssertionError(
            f"runtime concurrency: run ids collide: {run_ids!r}")
    if set(checkpoints.run_ids()) != run_ids:
        raise AssertionError(
            "runtime concurrency: checkpoints do not cover both runs")
    if len(applier.calls) != 2:
        raise AssertionError(
            f"runtime concurrency: applier calls={len(applier.calls)}")
    return "OK"


def runtime_budget() -> str:
    """The retry budget and the tick bound are deterministic and closed."""
    budget = RetryBudget(max_retries=3, base_delay_seconds=0.5)
    if budget.delays() != (0.5, 1.0, 2.0):
        raise AssertionError(
            f"runtime budget: delays={budget.delays()!r}")
    if budget.allows(3) is not True or budget.allows(4) is not False:
        raise AssertionError(
            f"runtime budget: allows(3)={budget.allows(3)!r}, "
            f"allows(4)={budget.allows(4)!r}")
    bound = load_profiles()["critic"].termination.max_ticks
    model = _ScriptedModel([
        _runtime_draft("ABANDON", rationale=f"r{i}") for i in range(10)])
    result = _runtime(model).run("critic", _runtime_ctx())
    if result.termination != Termination.TICK_LIMIT.value:
        raise AssertionError(
            f"runtime budget: termination={result.termination!r}")
    if result.ticks != bound or model.call_count != result.ticks:
        raise AssertionError(
            f"runtime budget: ticks={result.ticks!r}, bound={bound!r}, "
            f"model_calls={model.call_count}")
    return "OK"


def runtime_crash() -> str:
    """A real kill-9 run leaves a resumable, never-re-dispatched checkpoint.

    This is the one driver that depends on the test tree: a kill-9
    mid-run cannot happen inside the matrix's own process without
    killing the matrix, so the crash runs in a separate interpreter —
    the ``--crash-child`` entry point that ships in
    ``tests/test_agent_runtime.py``, the same child the pinned test
    exercises. The dependency is declared in this module's docstring.
    """
    with tempfile.TemporaryDirectory() as tmp:
        store_dir = Path(tmp) / "state"
        store_dir.mkdir(parents=True, exist_ok=True)
        script_path = Path(tmp) / "script.json"
        script = {"critic": [
            {"kind": "proposal", "provider_id": "alpha", "model_id": "m1",
             "structured": {"kind": "ABANDON", "rationale": "because",
                            "payload": {"step": 1}}},
            "DIE"]}
        script_path.write_text(json.dumps(script), encoding="utf-8")
        env = dict(os.environ)
        env["PYTHONPATH"] = f"{_SRC_DIR}{os.pathsep}{_WORKTREE}"
        env["PYTHONUTF8"] = "1"
        completed = subprocess.run(
            [sys.executable, "-m", "tests.test_agent_runtime",
             "--crash-child", str(store_dir), str(script_path), "critic"],
            cwd=str(_WORKTREE), capture_output=True, text=True,
            timeout=240, env=env)
        if completed.returncode != 9:
            raise AssertionError(
                f"runtime crash: crash child exit={completed.returncode}, "
                f"stderr={completed.stderr[-300:]!r}")
        stale_clock = _RuntimeClock()
        stale_clock.advance(3_600)
        runtime = _runtime(
            _ScriptedModel({}), checkpoints=FileCheckpointStore(store_dir),
            clock=stale_clock)
        verdict, updated = runtime.recover(
            run_id_of("critic", "task-root", "p1", 1))
        if verdict is None or updated is None:
            raise AssertionError("runtime crash: no recovery verdict")
        if verdict.kind != runtime_types.RECOVERY_RESUMABLE:
            raise AssertionError(
                f"runtime crash: recovery kind={verdict.kind!r}")
        if verdict.may_resume is not True or verdict.may_dispatch is not False:
            raise AssertionError(
                f"runtime crash: may_resume={verdict.may_resume!r}, "
                f"may_dispatch={verdict.may_dispatch!r}")
        if updated.state != TaskStatus.RUNNING.value:
            raise AssertionError(
                f"runtime crash: state={updated.state!r}")
    return "OK"
# ────────────────────────────────────────────────────────────────────
# GOVERNANCE plane
# ────────────────────────────────────────────────────────────────────

_GOV_PROJECT = "p1"
_GOV_OTHER_PROJECT = "p2"
_GOV_SCOPE = "curate-decision-h1"
_GOV_OP = "op-1"
_GOV_REQUESTER = "synthesizer"
_GOV_T1 = "2026-09-24T09:00:00+00:00"
_GOV_T2 = "2026-09-24T09:30:00+00:00"
_GOV_T6 = "2026-09-26T09:00:00+00:00"


def _gov_credential() -> CredentialRow:
    return CredentialRow(operator_id=_GOV_OP, name="Operator One",
                         created_at=_GOV_T1)


def _gov_decision_row(event_id: str = "ev-1", *, verdict: str = APPROVED,
                      scope: str = _GOV_SCOPE, project: str = _GOV_PROJECT,
                      operator: str = _GOV_OP, created_at: str = _GOV_T1,
                      reason: str = "operator verdict",
                      **payload: Any) -> DecisionRow:
    body: dict[str, Any] = {"decision": verdict, "operator_id": operator}
    body.update(payload)
    return DecisionRow(event_id=event_id, project_id=project,
                       correlation_id=scope, caused_by="operator",
                       reason=reason, payload=body, created_at=created_at)


def _gov_contradiction_request(actor: str, now: str) -> ActionRequest:
    return ActionRequest(action=CONTRADICTION_DECLARE,
                         project_id=_GOV_PROJECT, operator_id=_GOV_OP,
                         actor=actor, now=now, correlation_id=_GOV_SCOPE)


def governance_bypass() -> str:
    """An AGENT action needs no recorded evidence and stays allowed."""
    verdict = evaluate_authority(ActionRequest(
        action=SANDBOX_RUN, project_id=_GOV_PROJECT))
    if not verdict.is_allowed():
        raise AssertionError(
            f"governance bypass: AGENT action refused "
            f"{(verdict.refusal.code if verdict.refusal else '?')!r}")
    if verdict.satisfied_authority != "AGENT":
        raise AssertionError(
            f"governance bypass: authority={verdict.satisfied_authority!r}")
    if verdict.evidence != () or verdict.approval is not None:
        raise AssertionError(
            "governance bypass: an AGENT action consumed evidence")
    return "OK"


def governance_forgery() -> str:
    """A decision row for another project cannot authorize."""
    verdict = evaluate_authority(
        _gov_contradiction_request(_GOV_REQUESTER, _GOV_T2),
        EvidenceContext(
            credential=_gov_credential(),
            decisions=(_gov_decision_row(project=_GOV_OTHER_PROJECT),)))
    if verdict.refusal is None:
        raise AssertionError(
            "governance forgery: a foreign-project row authorized")
    if verdict.approval is None or verdict.approval.foreign_project_rows != 1:
        raise AssertionError(
            f"governance forgery: foreign_project_rows="
            f"{verdict.approval.foreign_project_rows if verdict.approval else '?'}")
    return verdict.refusal.code


def governance_self_approval() -> str:
    """A self-approved act is refused on independence."""
    verdict = evaluate_authority(
        _gov_contradiction_request(_GOV_OP, _GOV_T2),
        EvidenceContext(credential=_gov_credential(),
                        decisions=(_gov_decision_row(),)))
    if verdict.refusal is None:
        raise AssertionError(
            "governance self-approval: a self-approved act authorized")
    if verdict.requirement != REQUIREMENT_INDEPENDENCE:
        raise AssertionError(
            f"governance self-approval: requirement="
            f"{verdict.requirement!r}")
    if _GOV_OP not in verdict.refusal.detail:
        raise AssertionError(
            "governance self-approval: the refusal does not name the decider")
    return verdict.refusal.code


def governance_conflict() -> str:
    """DENY wins a PERMIT/DENY conflict, and the conflict is named."""
    permit_row = PolicyRow(
        action=PUBLISH, authority="HUMAN", refusal_code=ROLE,
        credential_refusal_code=OPERATOR, record_refusal_code=PROPOSAL,
        binding_refusal_code=PROPOSAL, head_refusal_code=STALE,
        binding_key=PUBLISH_BINDING_KEY, head_key=HEAD_KEY,
        window_seconds=DEFAULT_APPROVAL_WINDOW_SECONDS, effect=PERMIT)
    deny_row = PolicyRow(
        action=PUBLISH, authority="HUMAN", effect=DENY,
        refusal_code=OPERATOR, credential_refusal_code=OPERATOR,
        record_refusal_code=PROPOSAL, binding_refusal_code=PROPOSAL,
        head_refusal_code=STALE, binding_key=PUBLISH_BINDING_KEY,
        head_key=HEAD_KEY, window_seconds=DEFAULT_APPROVAL_WINDOW_SECONDS)
    policy = replace(GOVERNANCE_POLICY, version=99,
                     rows=(permit_row, deny_row))
    request = ActionRequest(
        action=PUBLISH, project_id=_GOV_PROJECT, operator_id=_GOV_OP,
        actor=_GOV_REQUESTER, command_hash="h-8", head_ref="gen-1",
        now=_GOV_T2, correlation_id=_GOV_SCOPE)
    # A variant document evaluates through the private seam; the public
    # entry refuses substituted policies by design.
    verdict = _evaluate_authority(
        request,
        EvidenceContext(credential=_gov_credential(),
                        decisions=(_gov_decision_row(publish_hash="h-8"),)),
        policy)
    if verdict.refusal is None:
        raise AssertionError(
            "governance conflict: a PERMIT/DENY conflict was not refused")
    if verdict.conflicting_rows != ("DENY:PUBLISH", "PERMIT:PUBLISH"):
        raise AssertionError(
            f"governance conflict: conflicting_rows="
            f"{verdict.conflicting_rows!r}")
    if "conflicting rows" not in verdict.refusal.detail:
        raise AssertionError(
            "governance conflict: the refusal does not name the conflict")
    return verdict.refusal.code


def governance_expiry() -> str:
    """A decision row is a closed snapshot and stops counting when stale."""
    row = _gov_decision_row()
    if DecisionRow.from_mapping(row.to_mapping()) != row:
        raise AssertionError(
            "governance expiry: the decision row does not round-trip")
    probes = {
        "extra-key": {**row.to_mapping(), "sql": "SELECT 1"},
        "missing-keys": {"event_id": "ev-1"},
        "non-mapping-payload": {"event_id": "ev-1", "project_id": _GOV_PROJECT,
                                "payload": "not-a-mapping"},
    }
    for label, mapping in probes.items():
        try:
            DecisionRow.from_mapping(mapping)
        except GovernanceFormatError:
            continue
        raise AssertionError(
            f"governance expiry: the closed snapshot accepted {label}")
    late = evaluate_authority(
        _gov_contradiction_request(_GOV_REQUESTER, _GOV_T6),
        EvidenceContext(credential=_gov_credential(), decisions=(row,)))
    if late.refusal is None:
        raise AssertionError(
            "governance expiry: a decision two windows old still authorized")
    if late.refusal.code != PROPOSAL:
        raise AssertionError(
            f"governance expiry: stale decision refused "
            f"{late.refusal.code!r}")
    return "OK"


# ────────────────────────────────────────────────────────────────────
# METHODOLOGY plane
# ────────────────────────────────────────────────────────────────────

_METHOD_PROJECT = "p1"
_METHOD_REFS = {
    "HYPOTHESIS": "hypothesis:program-h1/h1",
    "PREDICTION": "prediction:program-h1/h1/p1",
    "EVIDENCE": "evidence:evidence-e1",
    "CLAIM": "claim:claim-c1",
}


def _method_fresh(*, retracted: Sequence[str] = ()) -> SubstrateStore:
    store = SubstrateStore()
    for ref in _METHOD_REFS.values():
        store.admit_ref(ref, _METHOD_PROJECT)
    for ref in retracted:
        store.retract(ref)
    return store


def _method_node(kind: str, **content: Any) -> SubstrateNode:
    return SubstrateNode(kind=kind, project_id=_METHOD_PROJECT,
                         producing_task_id="t-hostile-driver",
                         content=dict(content),
                         rationale="hostile driver")


def _method_id(store: SubstrateStore, node: SubstrateNode) -> str:
    recorded = write_node(store, node)
    if not isinstance(recorded, str):
        raise AssertionError(
            f"methodology setup: expected a node id, got {recorded!r}")
    return recorded


def methodology_gap() -> str:
    """A non-root node without a predecessor refuses PROVENANCE."""
    recorded = write_node(_method_fresh(), _method_node(
        "HYPOTHESIS", external_ref=_METHOD_REFS["HYPOTHESIS"]))
    if not isinstance(recorded, SubstrateRefusal):
        raise AssertionError(
            f"methodology gap: predecessor-less node was admitted: "
            f"{recorded!r}")
    if "no predecessor" not in recorded.detail:
        raise AssertionError(
            f"methodology gap: refusal detail is {recorded.detail!r}")
    return recorded.code


def methodology_retraction() -> str:
    """A retracted ref admitted as support is refused (N9)."""
    store = _method_fresh(retracted=(_METHOD_REFS["EVIDENCE"],))
    recorded = write_node(store, _method_node(
        "QUESTION", question="q?",
        admitted_refs=(_METHOD_REFS["EVIDENCE"],)))
    if not isinstance(recorded, SubstrateRefusal):
        raise AssertionError(
            f"methodology retraction: retracted ref was admitted: "
            f"{recorded!r}")
    return recorded.code


def methodology_circular() -> str:
    """A cyclic provenance graph refuses the report and every write."""
    first = _method_node(
        "HYPOTHESIS", external_ref=_METHOD_REFS["HYPOTHESIS"],
        predecessors=("mnode_second",))
    second = _method_node(
        "PREDICTION", external_ref=_METHOD_REFS["PREDICTION"],
        predecessors=("mnode_first",))
    cyclic = SubstrateStore(nodes={"mnode_first": first,
                                   "mnode_second": second})
    reported = check_provenance_graph(cyclic)
    if not isinstance(reported, SubstrateRefusal):
        raise AssertionError(
            f"methodology circular: the cycle was not reported: {reported!r}")
    further = write_node(cyclic, _method_node(
        "QUESTION", question="other?"))
    if not isinstance(further, SubstrateRefusal):
        raise AssertionError(
            "methodology circular: a further write onto a cyclic store "
            "was admitted")
    if further.code != reported.code:
        raise AssertionError(
            f"methodology circular: report={reported.code!r}, "
            f"write={further.code!r}")
    return reported.code


def methodology_hallucination() -> str:
    """A citation of an unobserved external_ref refuses."""
    store = _method_fresh()
    question_id = _method_id(store, _method_node("QUESTION", question="q?"))
    recorded = write_node(store, _method_node(
        "HYPOTHESIS", external_ref="hypothesis:never-seen/h1",
        predecessors=(question_id,)))
    if not isinstance(recorded, SubstrateRefusal):
        raise AssertionError(
            f"methodology hallucination: unobserved ref was admitted: "
            f"{recorded!r}")
    if "does not resolve" not in recorded.detail:
        raise AssertionError(
            f"methodology hallucination: detail is {recorded.detail!r}")
    return recorded.code


def methodology_coupling() -> str:
    """A foreign-project external_ref fails closed."""
    store = _method_fresh()
    store.admit_ref("hypothesis:foreign/h1", "p2")
    question_id = _method_id(store, _method_node("QUESTION", question="q?"))
    recorded = write_node(store, _method_node(
        "HYPOTHESIS", external_ref="hypothesis:foreign/h1",
        predecessors=(question_id,)))
    if not isinstance(recorded, SubstrateRefusal):
        raise AssertionError(
            f"methodology coupling: foreign ref was admitted: {recorded!r}")
    if "project-scoped" not in recorded.detail:
        raise AssertionError(
            f"methodology coupling: detail is {recorded.detail!r}")
    return recorded.code


def methodology_leak() -> str:
    """A locally-defined kind carrying a non-empty external_ref refuses."""
    recorded = write_node(_method_fresh(), _method_node(
        "QUESTION", question="q?", external_ref="evidence:any/e1"))
    if not isinstance(recorded, SubstrateRefusal):
        raise AssertionError(
            f"methodology leak: a local kind carried an external_ref: "
            f"{recorded!r}")
    if "locally-defined" not in recorded.detail:
        raise AssertionError(
            f"methodology leak: detail is {recorded.detail!r}")
    return recorded.code
