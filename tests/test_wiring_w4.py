"""W4 wiring tests — the single wiring (`WIRING_DESIGN.md` BIND-4 + W1–W3).

This suite is the W4 slice's own evidence. It is deliberately self-contained
(its own in-memory spine, plane rig, model and profiles), so a change to
another slice's fixtures cannot silently weaken a wiring assertion. What it
proves, one group each:

- **tick → port → admission (capability, BIND-1)** — the controller dispatches
  a task whose template is a W1 capability template; the plane's port runs; the
  observation is admitted as an ordinary `INSERT_TASK` through the controller's
  own FENCED `apply_intent`; the task reaches SUCCEEDED through the wiring
  completion rule (there is no source outcome to query).
- **idempotent re-emit (BIND-1)** — the same dispatch re-emitted derives the
  same follow-up identity, so the spine answers duplicate and one row exists.
- **tick → wiring → driver (methodology, BIND-5)** — the task's spec carries the
  workflow document; the W3 driver runs every stage on the W2 runtime wiring
  under the controller's lease generation, and every stage admission is an
  ordinary intent that reached the one write path.
- **refusals-as-data** — a denied dispatch and an unhandled template are data,
  never exceptions and never silent successes.
- **lease-held / never a second writer** — a lease reclaimed mid-dispatch fails
  the bound write closed: the tick aborts to ``lock_lost`` with no admission.
- **the R4 refusal seam (BIND-3/4 §7 fixture)** — a spine `OPERATOR` reaches the
  caller **verbatim**; the other coercions are unchanged.
- **the gateway consult (BIND-4)** — the registered read-only preflight is
  consulted over the canonical policy, surfaces governance codes natively and
  maps only shape failures to the frozen `MALFORMED_PAYLOAD`.
- **no write surface / no new governance consumer** — mechanical pins.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path
from typing import Any

import pytest

import hermes.agents.runtime.run as run_module
from hermes.agents.runtime.config import load_profiles, parse_profile
from hermes.agents.runtime.types import (
    LOCK,
    MALFORMED_PAYLOAD,
    PROPOSAL,
    ROLE,
    RunLimits,
    TaskContext,
)
from hermes.agents.runtime.wiring import RuntimeWiring
from hermes.core.intents import Intent, IntentKind
from hermes.core.task_status import TaskStatus
from hermes.governance.authority import ActionRequest, evaluate_authority
from hermes.governance.policy import GOVERNANCE_POLICY, POLICY_SUBSTITUTION_DETAIL
from hermes.methodology.workflows import LITERATURE_REVIEW_DOCUMENT
from hermes.persistence.database import connect
from hermes.persistence.migrations import migrate_to_latest
from hermes.persistence.repositories import ProjectRepository, TaskRepository
from hermes.research.controller import Controller
from hermes.research.gateway import GatewayRejection, apply_intent
from hermes.research.task_handlers import (
    WIRING_TEMPLATE_FLAG,
    WiringTaskHandler,
    build_capability_handler,
    build_methodology_handler,
    handoff_to_handler_result,
)
from hermes.research.task_handlers.capability_handler import (
    UNHANDLED,
    CapabilityDispatchRegistry,
    CapabilityInvocation,
    ObservationHandoff,
)
from hermes.tools.capabilities.invoke import (
    CapabilityInvoker,
    InMemoryIdempotencyLedger,
)
from hermes.tools.capabilities.registry import CapabilityRegistry
from hermes.tools.capabilities.types import (
    Capability,
    CapabilityRefusal,
    InputField,
    RiskLevel,
    Tool,
    ToolGrant,
    ToolResult,
    ToolSet,
)
from hermes.tools.models.router import ModelProposal, ModelRequest

SRC_ROOT = Path(str(run_module.__file__)).parents[2]
PACKAGE_INIT = SRC_ROOT / "research" / "task_handlers" / "__init__.py"
GATEWAY_PATH = SRC_ROOT / "research" / "gateway.py"

PROJECT = "p1"
CLOCK = "2026-10-06T00:00:00.000000+00:00"
CAPABILITY = "cap.echo"
TOOL = "svc.echo"
TOOL_SET = "set.core"
CAP_TEMPLATE = "cap_echo"
METH_TEMPLATE = "methodology_run"
CHILD_TEMPLATE = "observation_review"
# Sentinel so ``CapabilityRig.handler`` can tell "no grant supplied" (the
# default — use the composition's real grant) apart from an explicit ``None``
# (the permission-first denial case).
_UNSET: Any = object()

REFS: dict[str, str] = {
    "HYPOTHESIS": "hypothesis:program-w4/h1",
    "PREDICTION": "prediction:program-w4/h1/p1",
    "EVIDENCE": "evidence:evidence-w4/e1",
    "CLAIM": "claim:claim-w4/c1",
}
STAGE_PROFILES = ("planner", "researcher", "experimenter", "verifier",
                  "synthesizer", "critic")


def _clock() -> str:
    return CLOCK


# ═══════════════════════ rigs and fakes ═══════════════════════


class _FakeClock:
    """The clock the capability plane needs (a monotonic number)."""

    def now_utc(self) -> str:
        return CLOCK

    def monotonic(self) -> float:
        return 1000.0


class _FakeLimiter:
    def acquire(self, capability_id: str) -> tuple[bool, str]:
        return (True, "")

    def release(self, capability_id: str) -> None:
        return None


class CapabilityRig:
    """A minimal coherent capability plane (W1's bridge over the real invoker)."""

    def __init__(self, *, reclaim: Any = None) -> None:
        self.registry = CapabilityRegistry(allowlist=frozenset({CAPABILITY}))
        self.registry.register_tool(Tool(
            tool_id=TOOL, summary="echo a declared string",
            inputs=(InputField(name="text", type="string"),)))
        self.registry.register_capability(Capability(
            capability_id=CAPABILITY, tool_id=TOOL, summary="echo"))
        self.registry.register_tool_set(ToolSet(
            set_id=TOOL_SET, capability_ids=(CAPABILITY,), summary="core"))
        self.received: list[dict[str, Any]] = []
        self._reclaim = reclaim

        def echo(arguments: dict[str, Any], context: Any) -> ToolResult:
            self.received.append(dict(arguments))
            if self._reclaim is not None:
                self._reclaim()
            payload = f"echo:{arguments.get('text', '')}"
            return ToolResult(payload=payload)

        self.invoker = CapabilityInvoker(
            registry=self.registry,
            implementations={TOOL: echo},
            clock=_FakeClock(),
            limiter=_FakeLimiter(),
            ledger=InMemoryIdempotencyLedger())
        self.bridge = CapabilityDispatchRegistry(plane=self.registry)
        self.bridge.register(CapabilityInvocation(
            template_key=CAP_TEMPLATE, capability_id=CAPABILITY,
            argument_fields=("text",), rationale="the W4 brief asks for it"))

    def handler(self, *, grant: Any = _UNSET) -> WiringTaskHandler:
        return build_capability_handler(
            template=CAP_TEMPLATE, registry=self.bridge, port=self.invoker,
            profile="analyst",
            grant=GRANT if grant is _UNSET else grant,
            admission_actor="RESEARCHER", child_template=CHILD_TEMPLATE)


GRANT = ToolGrant(grant_id="grant.1", profile="analyst",
                  tool_set_ids=frozenset({TOOL_SET}),
                  max_risk=RiskLevel.HIGH.value)


class ProposingModel:
    """A `ModelPort` proposing one ordinary `INSERT_TASK` per call."""

    def __init__(self) -> None:
        self.calls: list[ModelRequest] = []

    def invoke(self, request: ModelRequest) -> ModelProposal:
        self.calls.append(request)
        return ModelProposal(
            provider_id="scripted", model_id="scripted", tier="research",
            profile=request.profile,
            lease_generation=request.lease_generation,
            structured={"kind": "INSERT_TASK", "rationale": "because",
                        "payload": {"spec": {"goal": f"stage {request.profile}"}}})


class SilentModel:
    """A `ModelPort` that proposes nothing — a run with no durable effect."""

    def __init__(self) -> None:
        self.calls: list[ModelRequest] = []

    def invoke(self, request: ModelRequest) -> ModelProposal:
        self.calls.append(request)
        return ModelProposal(
            provider_id="scripted", model_id="scripted", tier="research",
            profile=request.profile,
            lease_generation=request.lease_generation,
            structured={})


class ToolCallingModel:
    """A `ModelPort` that emits one declared capability call."""

    def invoke(self, request: ModelRequest) -> ModelProposal:
        return ModelProposal(
            provider_id="scripted", model_id="scripted", tier="research",
            profile=request.profile,
            lease_generation=request.lease_generation,
            structured={
                "kind": "INSERT_TASK", "rationale": "because", "payload": {},
                "tool_calls": [{"capability_id": "source_search",
                                "arguments": {"query": "momentum"}}]})


class ScriptedCapabilities:
    """A `CapabilityPort` answering exactly what the test scripted."""

    def __init__(self, outcome: Any) -> None:
        self.outcome = outcome
        self.calls: list[Any] = []

    def invoke(self, request: Any) -> Any:
        self.calls.append(request)
        return self.outcome


class _Applied:
    """The shape `run._apply` reads off an injected Orchestration API result."""

    def __init__(self, *, duplicate: bool = False) -> None:
        self.entity_id = "ent-1"
        self.duplicate = duplicate


class _GrantingApplier:
    def __call__(self, intent: Intent) -> _Applied:
        return _Applied()


def _refusing_applier(code: str) -> Any:
    def applier(intent: Intent) -> Any:
        raise GatewayRejection(intent.kind, code, f"{code} detail")
    return applier


def _profile(name: str, *, tools: tuple[str, ...] = ()) -> Any:
    """A runtime profile proposing ordinary `INSERT_TASK`s only."""
    return parse_profile({
        "name": name,
        "role": f"{name} role",
        "agent_profile": "RESEARCHER",
        "model_policy": {"tier": "research", "structured_fields": ["proposals"]},
        "tools": list(tools),
        "authority": {"proposable_kinds": ["INSERT_TASK"]},
        "termination": {"max_ticks": 1, "max_proposals": 5,
                        "stop_when": "proposals_raised"},
    }, source=name)


def _stage_profiles() -> dict[str, Any]:
    return {name: _profile(name) for name in STAGE_PROFILES}


# ═══════════════════════ spine fixtures ═══════════════════════


def _spine() -> Any:
    conn = connect(":memory:")
    migrate_to_latest(conn)
    ProjectRepository(conn).create(PROJECT, "W4 test")
    return conn


def _admit(conn: Any, task_id: str, template: str,
           spec: dict[str, Any]) -> str:
    """Admit an AGENT_TASK through the ordinary gateway (lands PENDING)."""
    result = apply_intent(conn, Intent(
        kind=IntentKind.INSERT_TASK, proposed_by="DIRECTOR",
        project_id=PROJECT,
        payload={
            "task_id": task_id,
            "task_type": "AGENT_TASK",
            "spec": {"template": template, **spec},
            "idempotency_key": f"idem-{task_id}",
            "iteration": 1,
            "provenance": [],
            "inputs": [],
            "outputs": [],
            "dependencies": [],
            "cost_class": "LOW",
        }))
    return result.entity_id


def _controller(conn: Any, handlers: dict[str, Any]) -> Controller:
    return Controller(conn, project_id=PROJECT, task_handlers=handlers,
                      clock=_clock)


def _child_of(conn: Any, parent: str) -> str:
    from hermes.agents.runtime.types import child_task_id_of
    return child_task_id_of(parent, "RESEARCHER", 0)


def _status(conn: Any, task_id: str) -> str:
    return TaskRepository(conn).get_status(task_id).value


def _events(conn: Any) -> list[dict[str, Any]]:
    return [dict(row) for row in
            conn.execute("SELECT * FROM events ORDER BY created_at, event_id")]


# ═══════════════════════ 1. capability: tick → port → admission ═══════════


def test_a_capability_template_dispatches_through_the_port_to_admission() -> None:
    conn = _spine()
    try:
        rig = CapabilityRig()
        ctrl = _controller(conn, {CAP_TEMPLATE: rig.handler()})
        task_id = _admit(conn, "t-cap-1", CAP_TEMPLATE,
                         {"arguments": {"text": "hello"}})
        baseline = max(e["event_id"] for e in _events(conn))

        out = ctrl.tick()

        assert out.dispatched == [task_id]
        assert out.succeeded == [task_id]
        assert out.unhandled == []
        # the port ran, with the task's declared arguments
        assert rig.received == [{"text": "hello"}]
        # the observation was admitted as an ordinary follow-up task
        child = _child_of(conn, task_id)
        row = conn.execute("SELECT spec_json FROM tasks WHERE task_id = ?",
                           (child,)).fetchone()
        assert row is not None
        child_spec = json.loads(row["spec_json"])
        assert child_spec["template"] == CHILD_TEMPLATE
        assert child_spec["observation"]["status"] == "OK"
        assert child_spec["observation"]["capability_id"] == CAPABILITY
        # the follow-up task was admitted by the ONE write path — exactly one
        # ordinary INSERT_TASK landed during the tick (the audit payload names
        # the intent KIND, never the task id, so the tail isolates the tick)
        applied = [e for e in _events(conn)
                   if e["event_id"] > baseline
                   and e["event_type"] == "IntentApplied"
                   and '"intent_kind": "INSERT_TASK"' in e["payload_json"]]
        assert len(applied) == 1
        assert _status(conn, task_id) == TaskStatus.SUCCEEDED.value
    finally:
        conn.close()


def test_the_wiring_completion_rule_is_what_the_controller_reads() -> None:
    """The tick's SUCCEEDED is the W4 wiring branch, not a source outcome.

    Without the wiring-aware completion check, S6-B2 would query a source
    artifact for the wiring task, find none, and FAIL the honest success.
    """
    conn = _spine()
    try:
        rig = CapabilityRig()
        ctrl = _controller(conn, {CAP_TEMPLATE: rig.handler()})
        task_id = _admit(conn, "t-cap-2", CAP_TEMPLATE,
                         {"arguments": {"text": "hello"}})
        ctrl.tick()
        source_rows = conn.execute(
            "SELECT 1 FROM artifacts WHERE task_id = ? AND artifact_type IN "
            "('source_search','source_fetch_outcome')", (task_id,)).fetchall()
        assert source_rows == []
        assert _status(conn, task_id) == TaskStatus.SUCCEEDED.value
        # the bound entry is what the controller dispatched: it declares the
        # flag, and the class it belongs to owns the controller contract
        entry = rig.handler()
        assert getattr(entry, WIRING_TEMPLATE_FLAG) is True
        assert callable(entry.build_context)
    finally:
        conn.close()


def test_a_re_emitted_observation_is_idempotent() -> None:
    conn = _spine()
    try:
        rig = CapabilityRig()
        handler = rig.handler()
        task_id = _admit(conn, "t-cap-3", CAP_TEMPLATE,
                         {"arguments": {"text": "hello"}})
        entry = handler.bind_controller(
            orchestration=lambda intent: apply_intent(conn, intent,
                                                      clock=_clock),
            lease_generation=lambda: "7")
        task_row = {"task_id": task_id,
                    "idempotency_key": f"idem-{task_id}",
                    "spec": {"template": CAP_TEMPLATE,
                             "arguments": {"text": "hello"}}}
        ctx = entry.build_context(task_row, PROJECT, None)

        first = entry(ctx)
        second = entry(ctx)

        assert first.status == "completed" and first.outcome_recorded is True
        assert second.status == "completed" and second.outcome_recorded is True
        child = _child_of(conn, task_id)
        assert conn.execute("SELECT COUNT(*) c FROM tasks WHERE task_id = ?",
                            (child,)).fetchone()["c"] == 1
        # the plane replayed its own ledger rather than executing twice
        assert rig.received == [{"text": "hello"}]
    finally:
        conn.close()


# ═══════════════════════ 2. methodology: tick → wiring → driver ══════════


def test_a_methodology_template_drives_every_stage_through_the_bound_applier() -> None:
    conn = _spine()
    try:
        model = ProposingModel()
        handler = build_methodology_handler(model=model,
                                            profiles=_stage_profiles())
        ctrl = _controller(conn, {METH_TEMPLATE: handler})
        task_id = _admit(conn, "t-meth-1", METH_TEMPLATE, {
            "methodology": dict(LITERATURE_REVIEW_DOCUMENT),
            "inputs": {"question": "does it hold?",
                       "external_refs": REFS,
                       "admission_refs": list(REFS.values())},
        })
        baseline = max(e["event_id"] for e in _events(conn))

        out = ctrl.tick()

        assert out.dispatched == [task_id]
        assert out.succeeded == [task_id]
        assert _status(conn, task_id) == TaskStatus.SUCCEEDED.value
        # every declared stage ran on the runtime, under the controller's
        # lease generation (the wired attribution, B-4)
        assert len(model.calls) == len(LITERATURE_REVIEW_DOCUMENT["stages"])
        assert {request.lease_generation for request in model.calls} == {
            str(ctrl._lock_generation)}
        # every stage admission is an ordinary intent that landed through the
        # one write path — the child task ids are derived, never authored
        admitted = [e for e in _events(conn)
                    if e["event_id"] > baseline
                    and e["event_type"] == "IntentApplied"
                    and '"intent_kind": "INSERT_TASK"' in e["payload_json"]]
        assert len(admitted) == len(model.calls)
        assert conn.execute("SELECT COUNT(*) c FROM tasks").fetchone()["c"] > 1
    finally:
        conn.close()


def test_a_zero_admission_methodology_run_is_not_a_recorded_outcome() -> None:
    """S6-B2 at the wiring entry: a silent run recorded nothing, so it FAILED.

    A valid document with a model that proposes nothing runs every stage but
    reaches the one write path zero times; the entry must answer
    ``failed_typed`` / ``outcome_recorded=False`` (never a completion), the
    run's dispatch must add zero journal rows, and the tick must never
    SUCCEED the task.
    """
    conn = _spine()
    try:
        model = SilentModel()
        handler = build_methodology_handler(model=model,
                                            profiles=_stage_profiles())
        inputs = {"question": "does it hold?",
                  "external_refs": REFS,
                  "admission_refs": list(REFS.values())}
        task_id = _admit(conn, "t-meth-zero", METH_TEMPLATE, {
            "methodology": dict(LITERATURE_REVIEW_DOCUMENT),
            "inputs": inputs,
        })

        # the entry's own verdict, bound to this spine's one write path
        entry = handler.bind_controller(
            orchestration=lambda intent: apply_intent(conn, intent,
                                                      clock=_clock),
            lease_generation=lambda: "0")
        before = _events(conn)
        direct = entry(entry.build_context(
            {"task_id": task_id, "idempotency_key": f"idem-{task_id}",
             "spec": {"template": METH_TEMPLATE,
                      "methodology": dict(LITERATURE_REVIEW_DOCUMENT),
                      "inputs": inputs}},
            PROJECT, None))
        assert direct.status == "failed_typed"
        assert direct.outcome_recorded is False
        assert direct.reason.startswith("PROPOSAL:")
        assert "(S6-B2)" in direct.reason
        # zero journal rows from the run: no admission reached the write path
        assert _events(conn) == before

        # and the tick cannot read that run as a completion
        ctrl = _controller(conn, {METH_TEMPLATE: handler})
        baseline = max(e["event_id"] for e in _events(conn))
        out = ctrl.tick()
        assert out.dispatched == [task_id]
        assert out.succeeded == []
        assert out.retried == [task_id]
        assert _status(conn, task_id) == TaskStatus.RETRYING.value
        admitted = [e for e in _events(conn)
                    if e["event_id"] > baseline
                    and e["event_type"] == "IntentApplied"
                    and '"intent_kind": "INSERT_TASK"' in e["payload_json"]]
        assert admitted == []
    finally:
        conn.close()
# ═══════════════════════ 3. refusals are data ═══════════════════════


def test_a_denied_capability_dispatch_is_refusal_data() -> None:
    conn = _spine()
    try:
        rig = CapabilityRig()
        ctrl = _controller(conn, {CAP_TEMPLATE: rig.handler(grant=None)})
        task_id = _admit(conn, "t-cap-4", CAP_TEMPLATE,
                         {"arguments": {"text": "hello"}})

        out = ctrl.tick()

        assert out.dispatched == [task_id]
        assert out.succeeded == []
        assert rig.received == []              # the port was never reached
        assert conn.execute("SELECT COUNT(*) c FROM tasks WHERE task_id = ?",
                            (_child_of(conn, task_id),)).fetchone()["c"] == 0
        assert _status(conn, task_id) == TaskStatus.RETRYING.value
        assert out.retried == [task_id]
    finally:
        conn.close()


def test_an_unregistered_wiring_template_is_unhandled_by_the_tick() -> None:
    conn = _spine()
    try:
        ctrl = _controller(conn, {})           # nothing registered
        task_id = _admit(conn, "t-cap-5", CAP_TEMPLATE,
                         {"arguments": {"text": "hi"}})
        out = ctrl.tick()
        assert out.dispatched == []
        assert out.unhandled == [task_id]
        assert _status(conn, task_id) == TaskStatus.PENDING.value
    finally:
        conn.close()


def test_an_unbound_wiring_entry_fails_closed() -> None:
    rig = CapabilityRig()
    entry = rig.handler()
    ctx = entry.build_context({"task_id": "t"}, PROJECT, None)
    with pytest.raises(RuntimeError, match="bound by the controller"):
        entry(ctx)


# ═══════════════════════ 4. lease-held, never a second writer ════════════


def test_a_lease_reclaimed_mid_dispatch_fails_the_write_closed() -> None:
    """The bound applier writes on the FENCED connection.

    The capability tool reclaims the scheduler lease mid-dispatch (as a second
    controller would); the admission that follows must fail the fence, the tick
    must abort to ``lock_lost``, and no admission may land.
    """
    conn = _spine()

    def reclaim() -> None:
        conn.execute("UPDATE scheduler_lock SET owner = 'thief', "
                     "generation = generation + 1 WHERE id = 0")

    try:
        rig = CapabilityRig(reclaim=reclaim)
        ctrl = _controller(conn, {CAP_TEMPLATE: rig.handler()})
        task_id = _admit(conn, "t-cap-6", CAP_TEMPLATE,
                         {"arguments": {"text": "hello"}})

        out = ctrl.tick()

        assert out.idle == "lock_lost"
        assert out.succeeded == []
        assert rig.received == [{"text": "hello"}]     # the tool did run
        assert conn.execute("SELECT COUNT(*) c FROM tasks WHERE task_id = ?",
                            (_child_of(conn, task_id),)).fetchone()["c"] == 0
        assert "IntentApplied" not in {e["event_type"] for e in _events(conn)
                                       if task_id in (e["payload_json"] or "")}
    finally:
        conn.close()


# ═══════════════════════ 5. the R4 refusal seam (§7 fixture) ═════════════


def _wired_run(code: str) -> Any:
    wiring = RuntimeWiring(
        model=ProposingModel(),
        orchestration=_refusing_applier(code),
        lease_generation="lease-gen-w4",
        profiles={"planner": _profile("planner")})
    return wiring.run("planner", TaskContext(
        task_id="task-w4", project_id=PROJECT, lease_generation="lease-gen-w4"))


def test_a_spine_operator_refusal_survives_verbatim() -> None:
    wired = _wired_run("OPERATOR")
    assert wired.refusal_codes() == ("OPERATOR",)
    assert wired.result.proposals[0].admission_detail.startswith("OPERATOR:")


def test_the_other_spine_coercions_are_unchanged() -> None:
    assert _wired_run("SCOPE_NOT_GOVERNED").refusal_codes() == (PROPOSAL,)
    assert _wired_run("NOT_WIRED").refusal_codes() == (PROPOSAL,)
    assert _wired_run("LOCK").refusal_codes() == (LOCK,)


def test_the_capability_site_still_maps_a_foreign_code() -> None:
    """`run.py`'s shared constant at the capability site is unchanged."""
    from hermes.agents.runtime.run import AgentRuntime

    spy = ScriptedCapabilities(
        CapabilityRefusal(code="EVIDENCE_REF", detail="no such artifact"))
    runtime = AgentRuntime(
        model=ToolCallingModel(), orchestration=_GrantingApplier(),
        capabilities=spy, profiles=load_profiles())
    result = runtime.run("researcher", TaskContext(
        task_id="task-w4", project_id=PROJECT, lease_generation="gen-1",
        limits=RunLimits(max_ticks=1)))
    assert spy.calls                              # the port was reached
    assert result.refusal_codes() == (MALFORMED_PAYLOAD,)
    assert "EVIDENCE_REF" in result.refusals[0].detail


def test_the_plane_refusal_set_is_the_closed_six_plus_operator() -> None:
    assert frozenset(
        {PROPOSAL, ROLE, MALFORMED_PAYLOAD, LOCK, "RATIONALE", "STALE",
         "OPERATOR"}) == run_module._PLANE_REFUSAL_CODES


# ═══════════════════════ 6. the ObservationHandoff adaptation ════════════


def _handoff(**overrides: Any) -> ObservationHandoff:
    fields: dict[str, Any] = {"template_key": CAP_TEMPLATE,
                              "capability_id": CAPABILITY, "task_id": "t",
                              "project_id": PROJECT,
                              "lease_generation": "gen", "profile": "analyst",
                              "idempotency_key": "k", "status": "OK"}
    fields.update(overrides)
    return ObservationHandoff(**fields)


def test_the_handoff_adaptation_maps_every_shape() -> None:
    refused = handoff_to_handler_result(_handoff(
        status="REFUSED", rejected=True, code=ROLE, detail="no grant"))
    assert refused.status == "failed_typed"
    assert refused.reason.startswith("ROLE:")

    unhandled = handoff_to_handler_result(_handoff(status=UNHANDLED))
    assert unhandled.status == "failed_typed"
    assert unhandled.reason.startswith("unhandled")

    not_admitted = handoff_to_handler_result(_handoff())
    assert not_admitted.status == "failed_typed"
    assert not_admitted.reason.startswith(PROPOSAL)

    admitted = handoff_to_handler_result(_handoff(), admitted=True)
    assert admitted.status == "completed"
    assert admitted.outcome_recorded is True


# ═══════════════════════ 7. the gateway consult (BIND-4) ═════════════════


def _consult(action: str) -> Any:
    """A read-only consult over the PUBLIC entry and the canonical policy."""
    def consult(intent: Intent) -> None:
        verdict = evaluate_authority(ActionRequest(
            action=action, project_id=intent.project_id, actor="RESEARCHER"))
        if verdict.is_allowed():
            return
        refusal = verdict.refusal
        raise GatewayRejection(
            intent.kind, refusal.code if refusal is not None else ROLE,
            refusal.detail if refusal is not None else verdict.verdict)
    return consult


def test_the_registered_consult_allows_and_denies_natively() -> None:
    conn = _spine()
    try:
        task_id = _admit(conn, "t-consult-1", METH_TEMPLATE, {})
        # a second task, refused by the consult with the governance code
        refused_id = "t-consult-2"
        with pytest.raises(GatewayRejection) as caught:
            apply_intent(conn, Intent(
                kind=IntentKind.INSERT_TASK, proposed_by="DIRECTOR",
                project_id=PROJECT,
                payload={"task_id": refused_id, "task_type": "AGENT_TASK",
                         "spec": {"template": METH_TEMPLATE},
                         "idempotency_key": f"idem-{refused_id}",
                         "iteration": 1, "provenance": [], "inputs": [],
                         "outputs": [], "dependencies": [], "cost_class": "LOW"}),
                governance_consult=_consult("EVIDENCE_DELETE"))
        assert caught.value.code == ROLE          # native, verbatim
        assert conn.execute("SELECT 1 FROM tasks WHERE task_id = ?",
                            (refused_id,)).fetchone() is None
        # the refusal is journalled as data
        assert any(e["event_type"] == "IntentRejected" for e in _events(conn))
        # the same seam admits when governance allows
        assert conn.execute("SELECT 1 FROM tasks WHERE task_id = ?",
                            (task_id,)).fetchone() is not None
    finally:
        conn.close()


def test_a_substituted_policy_refusal_surfaces_its_frozen_code() -> None:
    """The canonical document is bound at the public entry — refused as data."""

    def substituted(intent: Intent) -> None:
        # handing the shipped document back is refused by the public entry
        verdict = evaluate_authority(
            ActionRequest(action="WEB_SEARCH", project_id=intent.project_id,
                          actor="RESEARCHER"),
            None, policy=GOVERNANCE_POLICY)
        assert verdict.refusal is not None
        raise GatewayRejection(intent.kind, verdict.refusal.code,
                               verdict.refusal.detail)

    conn = _spine()
    try:
        with pytest.raises(GatewayRejection) as caught:
            apply_intent(conn, Intent(
                kind=IntentKind.INSERT_TASK, proposed_by="DIRECTOR",
                project_id=PROJECT,
                payload={"task_id": "t-sub-1", "task_type": "AGENT_TASK",
                         "spec": {}, "idempotency_key": "idem-t-sub-1",
                         "iteration": 1, "provenance": [], "inputs": [],
                         "outputs": [], "dependencies": [], "cost_class": "LOW"}),
                governance_consult=substituted)
        assert caught.value.code == MALFORMED_PAYLOAD
        assert POLICY_SUBSTITUTION_DETAIL in str(caught.value)
    finally:
        conn.close()


def test_a_broken_consult_maps_to_the_frozen_shape_code() -> None:
    def broken(intent: Intent) -> None:
        raise ValueError("the consult itself is mis-wired")

    conn = _spine()
    try:
        with pytest.raises(GatewayRejection) as caught:
            apply_intent(conn, Intent(
                kind=IntentKind.INSERT_TASK, proposed_by="DIRECTOR",
                project_id=PROJECT,
                payload={"task_id": "t-broken-1", "task_type": "AGENT_TASK",
                         "spec": {}, "idempotency_key": "idem-t-broken-1",
                         "iteration": 1, "provenance": [], "inputs": [],
                         "outputs": [], "dependencies": [], "cost_class": "LOW"}),
                governance_consult=broken)
        assert caught.value.code == MALFORMED_PAYLOAD   # frozen, never invented
        assert "governance consult refused" in caught.value.reason
    finally:
        conn.close()


def test_the_consult_is_read_only() -> None:
    """A refusal changes nothing but the audit row (no writer, no row)."""
    conn = _spine()
    try:
        before_tasks = conn.execute("SELECT COUNT(*) c FROM tasks").fetchone()["c"]
        before_events = len(_events(conn))
        with pytest.raises(GatewayRejection):
            apply_intent(conn, Intent(
                kind=IntentKind.INSERT_TASK, proposed_by="DIRECTOR",
                project_id=PROJECT,
                payload={"task_id": "t-ro-1", "task_type": "AGENT_TASK",
                         "spec": {}, "idempotency_key": "idem-t-ro-1",
                         "iteration": 1, "provenance": [], "inputs": [],
                         "outputs": [], "dependencies": [], "cost_class": "LOW"}),
                governance_consult=_consult("PUBLISH"))
        assert conn.execute("SELECT COUNT(*) c FROM tasks").fetchone()["c"] == \
            before_tasks
        after = _events(conn)
        assert len(after) == before_events + 1     # only the IntentRejected row
        assert after[-1]["event_type"] == "IntentRejected"
    finally:
        conn.close()


# ═══════════════════════ 8. mechanical discipline ═══════════════════════


def test_no_wiring_file_names_the_governance_module() -> None:
    """BIND-4's consumer set does not grow: no spine file reaches the plane."""
    for path in (PACKAGE_INIT, GATEWAY_PATH):
        assert "hermes.governance" not in path.read_text(encoding="utf-8"), path


def test_the_registration_export_holds_no_write_surface() -> None:
    source = PACKAGE_INIT.read_text(encoding="utf-8")
    tree = ast.parse(source)
    banned_imports = ("hermes.persistence", "hermes.research.gateway",
                      "hermes.research.repositories", "sqlite3")
    banned_names = {"conn", "cursor", "execute", "executemany", "commit",
                    "rollback", "sqlite3", "_append_event_to_db",
                    "repositories", "BEGIN IMMEDIATE"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert not alias.name.startswith(banned_imports), alias.name
        elif isinstance(node, ast.ImportFrom) and node.module:
            assert not node.module.startswith(banned_imports), node.module
    names = {node.id for node in ast.walk(tree)
             if isinstance(node, ast.Name)}
    names |= {node.attr for node in ast.walk(tree)
              if isinstance(node, ast.Attribute)}
    assert names & banned_names == set()


def test_the_entry_declares_the_controller_contract() -> None:
    rig = CapabilityRig()
    entry = build_methodology_handler(model=ProposingModel(),
                                      profiles=_stage_profiles())
    for candidate in (rig.handler(), entry):
        assert getattr(candidate, WIRING_TEMPLATE_FLAG) is True
        assert callable(getattr(candidate, "build_context"))
        assert callable(getattr(candidate, "bind_controller"))
