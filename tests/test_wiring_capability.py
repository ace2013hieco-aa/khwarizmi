"""W1 wiring tests — the capability dispatch bridge (`BIND-1`).

These fixtures prove the *binding* (`WIRING_DESIGN.md` §7 "BIND-1"), not the
capability plane itself (that is `tests/test_capability_plane.py`). The suite is
self-contained: it builds its own minimal registry, grant and invoker rather than
reaching into the plane's fixtures, so a change to the plane's fixtures cannot
silently weaken a wiring assertion.

Four properties, one group of tests each:

- **unhandled until registered** — an unknown template key resolves to the
  `"unhandled"` sentinel, dispatching it touches no port, and registering the key
  is the only thing that changes that;
- **permission before execution** — a denied dispatch refuses `ROLE` as data and
  runs no tool, consumes no rate token and opens no idempotency record; a
  *neutralized* permission check still kills execution, proving the check is
  consulted before the port rather than after a call;
- **the handoff shape** — a real plane observation arrives envelope-wrapped, with
  the bounded provenance note, the task/lease attribution, and no payload text in
  any record form;
- **no write surface** — the module's imports are checked by AST against an exact
  allowlist, so it cannot reach persistence, SQL or the gateway.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path
from typing import Any

import pytest

import hermes.research.task_handlers.capability_handler as capability_handler
from hermes.research.task_handlers.capability_handler import (
    REFUSED,
    UNHANDLED,
    CapabilityDispatchRegistry,
    CapabilityInvocation,
    CapabilityPort,
    DispatchContext,
    ObservationHandoff,
)
from hermes.security.boundaries import UntrustedContent
from hermes.tools.capabilities.invoke import (
    CapabilityInvoker,
    InMemoryIdempotencyLedger,
)
from hermes.tools.capabilities.registry import CapabilityRegistry
from hermes.tools.capabilities.types import (
    IDEMPOTENCY_CONFLICT,
    MALFORMED_PAYLOAD,
    ROLE,
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
from hermes.tools.research_sources import ProviderValidationError

MODULE_PATH = Path(str(capability_handler.__file__))
CONTROLLER_PATH = MODULE_PATH.parents[1] / "controller.py"

TEMPLATE_KEY = "cap_echo"
CAPABILITY = "cap.echo"
TOOL = "svc.echo"
TOOL_SET = "set.core"
PROJECT = "proj-1"
TASK = "task-1"
LEASE = "lease-gen-7"
PAYLOAD = "echo:hello"


# ── a minimal, coherent plane ──


def build_registry() -> CapabilityRegistry:
    registry = CapabilityRegistry(allowlist=frozenset({CAPABILITY}))
    registry.register_tool(Tool(
        tool_id=TOOL, summary="echo a declared string",
        inputs=(InputField(name="text", type="string"),)))
    registry.register_capability(Capability(
        capability_id=CAPABILITY, tool_id=TOOL, summary="echo"))
    registry.register_tool_set(ToolSet(
        set_id=TOOL_SET, capability_ids=(CAPABILITY,), summary="core"))
    return registry


GRANT = ToolGrant(grant_id="grant.1", profile="analyst",
                  tool_set_ids=frozenset({TOOL_SET}),
                  max_risk=RiskLevel.HIGH.value)
GRANT_OTHER_PROFILE = ToolGrant(grant_id="grant.2", profile="someone-else",
                                tool_set_ids=frozenset({TOOL_SET}),
                                max_risk=RiskLevel.HIGH.value)
GRANT_OPENS_NOTHING = ToolGrant(grant_id="grant.3", profile="analyst",
                                tool_set_ids=frozenset(),
                                max_risk=RiskLevel.HIGH.value)


class FakeClock:
    """A clock with no time in it — the plane only needs a monotonic number."""

    def __init__(self) -> None:
        self.t = 1000.0

    def now_utc(self) -> str:
        return "2026-10-06T12:00:00+00:00"

    def monotonic(self) -> float:
        return self.t


class FakeLimiter:
    """Structural stand-in for the provider rate limiter (atomic decision+cause)."""

    def __init__(self, *, granted: bool = True) -> None:
        self.granted = granted
        self.acquires: list[str] = []
        self.releases: list[str] = []

    def acquire(self, capability_id: str) -> tuple[bool, str]:
        self.acquires.append(capability_id)
        return (self.granted, "" if self.granted else "denied")

    def release(self, capability_id: str) -> None:
        self.releases.append(capability_id)


class Rig:
    """One wired bridge over a recording invoker."""

    def __init__(self) -> None:
        self.registry = build_registry()
        self.limiter = FakeLimiter()
        self.ledger = InMemoryIdempotencyLedger()
        self.calls: list[str] = []
        self.received: list[dict[str, Any]] = []

        def echo(arguments: dict[str, Any], context: ToolCallContext
                 ) -> ToolResult:
            self.calls.append(TOOL)
            self.received.append(dict(arguments))
            return ToolResult(payload=f"echo:{arguments.get('text', '')}")

        self.invoker = CapabilityInvoker(
            registry=self.registry,
            implementations={TOOL: echo},
            clock=FakeClock(),
            limiter=self.limiter,
            ledger=self.ledger)
        self.bridge = CapabilityDispatchRegistry(plane=self.registry)
        self.bridge.register(CapabilityInvocation(
            template_key=TEMPLATE_KEY, capability_id=CAPABILITY,
            argument_fields=("text",), rationale="the brief asks for it"))

    def context(self, *, grant: ToolGrant | None = GRANT,
                profile: str = "analyst", arguments: dict[str, Any] | None = None,
                key: str = "idem-1") -> DispatchContext:
        return DispatchContext(
            task_id=TASK, project_id=PROJECT, lease_generation=LEASE,
            profile=profile, idempotency_key=key,
            grant=grant,
            arguments=dict(arguments if arguments is not None else {"text": "hello"}))

    def dispatch(self, *, key: str = TEMPLATE_KEY,
                 context: DispatchContext | None = None,
                 port: CapabilityPort | None = None) -> ObservationHandoff:
        return self.bridge.dispatch(
            key, port=port if port is not None else self.invoker,
            context=context if context is not None else self.context())


class KillPort:
    """A port that fails the suite if it is ever reached."""

    def __init__(self) -> None:
        self.calls = 0

    def invoke(self, request: InvokeRequest) -> Observation | CapabilityRefusal:
        self.calls += 1
        raise AssertionError("the capability port was invoked")


# ── 1. unhandled until registered ──


def test_an_unregistered_key_is_unhandled() -> None:
    bridge = CapabilityDispatchRegistry(plane=build_registry())
    assert bridge.keys() == ()
    assert bridge.classify(TEMPLATE_KEY) == UNHANDLED
    assert bridge.resolve(TEMPLATE_KEY) is None


def test_dispatching_an_unregistered_key_touches_no_port() -> None:
    bridge = CapabilityDispatchRegistry(plane=build_registry())
    port = KillPort()
    result = bridge.dispatch(TEMPLATE_KEY, port=port, context=Rig().context())
    assert result.status == UNHANDLED
    assert result.rejected is False
    assert result.code == ""
    assert result.provenance == {}
    assert result.envelope_complete is False
    assert port.calls == 0


def test_registering_a_key_is_what_makes_it_dispatchable() -> None:
    bridge = CapabilityDispatchRegistry(plane=build_registry())
    assert bridge.classify(TEMPLATE_KEY) == UNHANDLED
    bridge.register(CapabilityInvocation(template_key=TEMPLATE_KEY,
                                         capability_id=CAPABILITY))
    assert bridge.classify(TEMPLATE_KEY) == TEMPLATE_KEY
    assert bridge.keys() == (TEMPLATE_KEY,)
    assert bridge.classify("still-not-a-key") == UNHANDLED


def test_unhandled_matches_the_controllers_own_sentinel() -> None:
    """The bridge and the tick must use the same word for "no executor"."""
    assert UNHANDLED == "unhandled"
    source = CONTROLLER_PATH.read_text(encoding="utf-8")
    assert f'"{UNHANDLED}"' in source


def test_registration_fails_closed() -> None:
    bridge = CapabilityDispatchRegistry(plane=build_registry())
    with pytest.raises(ProviderValidationError):
        bridge.register(CapabilityInvocation(template_key="  ",
                                             capability_id=CAPABILITY))
    with pytest.raises(ProviderValidationError):
        bridge.register(CapabilityInvocation(template_key="ghost_key",
                                             capability_id="cap.ghost"))
    bridge.register(CapabilityInvocation(template_key=TEMPLATE_KEY,
                                         capability_id=CAPABILITY))
    with pytest.raises(ProviderValidationError):
        bridge.register(CapabilityInvocation(template_key=TEMPLATE_KEY,
                                             capability_id=CAPABILITY))


def test_keys_are_normalised_like_the_tick_normalises_a_template() -> None:
    bridge = CapabilityDispatchRegistry(plane=build_registry())
    bridge.register(CapabilityInvocation(template_key="  Cap_Echo ",
                                         capability_id=CAPABILITY))
    assert bridge.keys() == (TEMPLATE_KEY,)
    assert bridge.classify("CAP_ECHO") == TEMPLATE_KEY


# ── 2. permission before execution ──


def test_a_dispatch_without_a_grant_refuses_role_as_data() -> None:
    rig = Rig()
    result = rig.dispatch(context=rig.context(grant=None))
    assert result.rejected is True
    assert result.code == ROLE
    assert result.status == REFUSED
    assert rig.calls == []
    assert rig.limiter.acquires == []
    assert rig.ledger.get("idem-1") is None
    assert result.provenance == {}


def test_a_grant_bound_to_another_profile_refuses_role() -> None:
    rig = Rig()
    result = rig.dispatch(context=rig.context(grant=GRANT_OTHER_PROFILE))
    assert (result.rejected, result.code) == (True, ROLE)
    assert rig.calls == []


def test_a_grant_that_opens_no_tool_set_refuses_role() -> None:
    rig = Rig()
    result = rig.dispatch(context=rig.context(grant=GRANT_OPENS_NOTHING))
    assert (result.rejected, result.code) == (True, ROLE)
    assert rig.calls == []


def test_an_authorized_dispatch_runs_the_tool() -> None:
    rig = Rig()
    result = rig.dispatch()
    assert result.rejected is False
    assert result.status == "OK"
    assert rig.calls == [TOOL]
    assert rig.limiter.acquires == [CAPABILITY]


def test_a_neutralized_permission_check_still_kills_execution(monkeypatch
                                                              ) -> None:
    """If the check denies, nothing runs — so the check precedes the call."""
    rig = Rig()
    monkeypatch.setattr(CapabilityDispatchRegistry, "denial_for",
                        lambda self, invocation, context: "neutralized")
    result = rig.dispatch()
    assert (result.rejected, result.code) == (True, ROLE)
    assert rig.calls == []
    assert rig.limiter.acquires == []


def test_permission_is_decided_before_the_schema_is_checked() -> None:
    """A denied dispatch with a malformed argument is a ROLE denial, not a schema one."""
    rig = Rig()
    result = rig.dispatch(context=rig.context(grant=None,
                                              arguments={"text": "x", "bogus": 1}))
    assert result.code == ROLE
    assert rig.calls == []


def test_an_undeclared_argument_refuses_malformed_payload_before_execution() -> None:
    rig = Rig()
    result = rig.dispatch(context=rig.context(arguments={"text": "x", "bogus": 1}))
    assert (result.rejected, result.code) == (True, MALFORMED_PAYLOAD)
    assert "bogus" in result.detail
    assert rig.calls == []
    assert rig.limiter.acquires == []


# ── 3. the observation→provenance handoff ──


def test_a_successful_dispatch_hands_off_an_envelope_wrapped_observation() -> None:
    rig = Rig()
    result = rig.dispatch()
    assert isinstance(result, ObservationHandoff)
    assert isinstance(result.payload, UntrustedContent)
    assert result.payload_text() == PAYLOAD
    assert str(result.payload) != PAYLOAD          # the marker, never the text
    assert result.envelope_complete is True
    assert result.observation_digest != ""
    assert set(result.provenance) == {
        "envelope_version", "reconstruct", "inputs_digest", "observation_digest",
        "authority", "failure", "complete"}
    assert result.provenance["complete"] is True
    assert result.provenance["authority"] == "GRANTED"


def test_the_handoff_is_attributed_to_the_dispatched_task() -> None:
    rig = Rig()
    result = rig.dispatch()
    assert (result.template_key, result.capability_id) == (TEMPLATE_KEY, CAPABILITY)
    assert (result.task_id, result.project_id) == (TASK, PROJECT)
    assert result.lease_generation == LEASE
    assert result.profile == "analyst"
    assert result.idempotency_key == "idem-1"


def test_the_record_form_carries_no_payload_text_and_no_identity() -> None:
    rig = Rig()
    record = rig.dispatch().as_record()
    assert json.loads(json.dumps(record)) == record  # bounded, serialisable data
    assert PAYLOAD not in json.dumps(record)
    assert PAYLOAD not in json.dumps(record["provenance"])
    assert "id" not in record


def test_a_plane_refusal_keeps_the_frozen_code_and_its_provenance() -> None:
    rig = Rig()
    rig.dispatch(key=TEMPLATE_KEY, context=rig.context(arguments={"text": "one"}))
    result = rig.dispatch(key=TEMPLATE_KEY,
                          context=rig.context(arguments={"text": "two"}))
    assert (result.rejected, result.code) == (True, IDEMPOTENCY_CONFLICT)
    assert result.status == REFUSED
    assert result.payload is None
    assert result.envelope_complete is True
    assert rig.calls == [TOOL]  # the second call never executed


def test_a_replay_returns_the_remembered_observation_without_re_executing() -> None:
    rig = Rig()
    first = rig.dispatch()
    second = rig.dispatch()
    assert first.replayed is False
    assert second.replayed is True
    assert second.payload_text() == PAYLOAD
    assert second.status == "OK"
    assert rig.calls == [TOOL]


# ── 4. no write surface ──

#: The exact import set the handler is allowed. Extending this list is a design
#: decision, not a convenience: the bridge must never reach a repository, a
#: connection, or the gateway.
ALLOWED_IMPORTS = frozenset({
    "__future__",
    "dataclasses",
    "typing",
    "hermes.security.boundaries",
    "hermes.tools.capabilities.envelope",
    "hermes.tools.capabilities.registry",
    "hermes.tools.capabilities.types",
    "hermes.tools.research_sources",
})


def _imports_of(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
    return names


def test_the_handler_imports_ports_and_core_types_only() -> None:
    assert _imports_of(MODULE_PATH) == set(ALLOWED_IMPORTS)


#: Names a module with a write surface would have to mention. Collected by AST
#: from the code (not the prose), so the test cannot be satisfied by wording.
FORBIDDEN_NAMES = frozenset({
    "conn", "connection", "cursor", "commit", "rollback", "executemany",
    "execute", "BEGIN", "sqlite3",
})


def _code_identifiers(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            found.add(node.id)
        elif isinstance(node, ast.Attribute):
            found.add(node.attr)
    return found


def test_the_handler_never_names_a_writer_or_a_transaction() -> None:
    assert _code_identifiers(MODULE_PATH) & FORBIDDEN_NAMES == set()
