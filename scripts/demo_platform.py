#!/usr/bin/env python3
"""PLATFORM-DEMO - the hermetic platform walkthrough (recording-ready).

One deterministic run, offline, credential-free. It drives the four
platform planes DIRECTLY, the way a test does - nothing here wires a plane
into production, and the stack stays unwired (the O1/O3/O4/O5 deferral
stands):

  BEAT 1  the frame is hermetic   - prove the run before believing it
  BEAT 2  the model plane routes  - a request -> a proposal, accounted
  BEAT 3  the capability plane    - a permissioned invoke -> an observation
  BEAT 4  the runtime plane       - run -> delegate -> checkpoint/resume
  BEAT 5  the governance plane    - a check over the result (allow + refuse)
  BEAT 6  refusals are data       - every plane refuses, and refuses as data

Every beat prints one line of narration plus the REAL output of the thing
it just ran. Nothing is hard-coded as "expected": the account rows, the
envelope, the admission verdicts and the governance verdicts are read off
the objects the planes returned.

Hermetic by construction
------------------------
The socket layer is blocked BEFORE ``hermes`` is imported (a demo that
silently reached the network would not be replayable by a judge offline).
The planes hold no store: the runtime's checkpoint and delegation state
are in-memory only, the capability ledger is in-process, and the clock is
frozen at one instant. No credential is read or required - the operator
token is a local fixture labelled as such, and the planes never carry a
credential field.

Self-verifying
--------------
The script carries a check ledger and an exit-code contract: 0 = every
check passed, 1 = at least one check failed, 2 = the demo body raised
(traceback printed, never swallowed). Every repo file it reads to derive
an expectation is cited as ``path:line`` and the citation is PROVEN by
re-reading that exact line, so a drifted oracle fails the demo loudly
instead of silently shifting the story.

Replay determinism
------------------
Every line this script emits is hashed (after masking clock/temp values)
into a REPLAY DIGEST. Two consecutive runs must print the same digest:
running it twice in the same environment is byte-identical evidence, and
the digest is what makes "it ran twice in a row" checkable rather than
asserted.

Exit-contract proof (mutation)
------------------------------
``DEMO_PLATFORM_MUTATION=check`` forces one ledger check to fail (EXIT 1);
``DEMO_PLATFORM_MUTATION=raise`` raises inside the demo body (EXIT 2). Both
are used to prove the 0/1/2 contract without touching the happy path.

Run (from the repository root, with the project venv):

  .venv/Scripts/python.exe scripts/demo_platform.py         # Windows
  .venv/bin/python scripts/demo_platform.py                 # POSIX
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import socket
import sys
import time
import traceback
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]

# ── Beat 1a: the hermetic guard, installed BEFORE hermes is imported ──


class NetworkBlocked(RuntimeError):
    pass


def _blocked_network(*_args: object, **_kwargs: object) -> Any:
    raise NetworkBlocked("PLATFORM-DEMO is hermetic: network use refused")


socket.socket = _blocked_network              # type: ignore[assignment,misc]
socket.create_connection = _blocked_network   # type: ignore[assignment]
socket.getaddrinfo = _blocked_network         # type: ignore[assignment]

sys.path.insert(0, str(REPO_ROOT / "src"))

from hermes.agents.runtime.checkpoint import InMemoryCheckpointStore  # noqa: E402
from hermes.agents.runtime.config import load_profiles  # noqa: E402
from hermes.agents.runtime.delegate import InMemoryDelegationStore  # noqa: E402
from hermes.agents.runtime.run import AgentRuntime  # noqa: E402
from hermes.agents.runtime.types import (  # noqa: E402
    MALFORMED_PAYLOAD,
    Admission,
    DelegationState,
    ProposalSet,
    RunLimits,
    TaskContext,
    digest_of,
)
from hermes.core.intents import Intent  # noqa: E402
from hermes.governance.authority import (  # noqa: E402
    ALLOWED,
    REFUSED,
    ActionRequest,
    CredentialRow,
    EvidenceContext,
    evaluate_authority,
)
from hermes.governance.policy import CONTRADICTION_DECLARE, WEB_SEARCH  # noqa: E402
from hermes.research.gateway import IntentResult  # noqa: E402
from hermes.security.boundaries import UntrustedContent  # noqa: E402
from hermes.tools.capabilities.invoke import (  # noqa: E402
    CapabilityInvoker,
    InMemoryIdempotencyLedger,
)
from hermes.tools.capabilities.registry import CapabilityRegistry  # noqa: E402
from hermes.tools.capabilities.types import (  # noqa: E402
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
from hermes.tools.models.router import (  # noqa: E402
    FieldSpec,
    ModelPlanePolicy,
    ModelProfile,
    ModelProposal,
    ModelRefusal,
    ModelRequest,
    ModelResponse,
    ModelRouter,
    OutputContract,
    TokenUsage,
)

CLOCK = "2026-01-01T00:00:00.000000+00:00"
PROJECT_ID = "p1"
LEASE = "lease-gen-7"
OP_ID = "platform-op"
SCOPE = "contradiction-scope-1"
# Local fixture credential: registered in memory by this script, never a
# real secret, never read from the environment or from disk.
OP_TOKEN = "platform-demo-local-fixture"

BUDGET_SECONDS = 120.0

QUESTION = ("Does a low-volatility regime condition the momentum-to-reversal "
            "flip in the cross-section?")

# The shipped planes this demo drives directly.
MODEL_PLANE = "src/hermes/tools/models/router.py"
CAP_PLANE = "src/hermes/tools/capabilities"
RUNTIME_PLANE = "src/hermes/agents/runtime"
GOV_PLANE = "src/hermes/governance"

# ── episode capture: everything printed, for the replay digest ──

EPISODE: list[str] = []


def out(text: str = "") -> None:
    print(text, flush=True)
    EPISODE.append(text)


def banner(title: str) -> None:
    out("-" * 74)
    out(title)


# ── the check ledger ──

CHECKS: list[tuple[str, bool, str]] = []


def check(label: str, ok: bool, detail: str = "") -> bool:
    CHECKS.append((label, bool(ok), detail))
    mark = "[PASS]" if ok else "[FAIL]"
    out(f"  {mark} {label}" + (f" - {detail}" if detail else ""))
    return bool(ok)


def passed() -> int:
    return sum(1 for _, ok, _ in CHECKS if ok)


# ── repo citations: every oracle read is proven line-by-line ──

CITATIONS: list[str] = []


def cite(rel: str, needle: str, expect_line: int | None = None) -> str:
    """Prove that ``rel`` contains ``needle`` at ``expect_line``.

    A wrong line, a moved needle or a missing file is a FAILING check - the
    demo's expectations are never taken on faith.
    """
    path = REPO_ROOT / rel
    if not path.exists():
        check(f"citation {rel} exists", False, "file not found")
        return f"{rel}:MISSING"
    text = path.read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines()
    found = None
    for number, line in enumerate(lines, start=1):
        if needle in line:
            found = number
            break
    if found is None:
        check(f"citation {rel}:{expect_line} holds", False,
              f"needle {needle!r} not present")
        return f"{rel}:MISSING"
    ok = expect_line is None or found == expect_line
    check(f"citation {rel}:{found} holds", ok,
          "" if ok else f"expected line {expect_line}, found {found}")
    citation = f"{rel}:{found}"
    CITATIONS.append(citation)
    return citation


# ── the frozen frame: one clock for every plane ──


class DemoClock:
    """A frozen clock: one instant, no sleeping, fixed monotonic.

    Satisfies every plane's clock shape at once: ``now_utc()`` (model +
    capability planes), ``monotonic()`` (capability deadline), ``sleep``
    (model backoff, recorded) and ``__call__`` (the runtime's zero-arg
    ``Clock``).
    """

    def __init__(self, stamp: str = CLOCK, monotonic: float = 1000.0) -> None:
        self._stamp = stamp
        self._monotonic = monotonic
        self.sleeps: list[float] = []

    def now_utc(self) -> str:
        return self._stamp

    def monotonic(self) -> float:
        return self._monotonic

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)

    def __call__(self) -> str:
        return self._stamp


CLOCK_OBJ = DemoClock()


# ── BEAT 1: the frame is hermetic ──


def beat_frame() -> None:
    banner("BEAT 1 - THE FRAME IS HERMETIC")
    out("  > prove the frame before believing anything that follows")
    out(f"  interpreter : {sys.executable}")
    import hermes as _hermes  # attestation only: prove which tree loaded

    hermes_path = Path(_hermes.__file__).resolve()
    out(f"  hermes      : {hermes_path}")
    out(f"  clock       : {CLOCK}")
    out("  storage     : the planes hold no store; checkpoint/delegation "
        "state is in-memory only")

    raised: Exception | None = None
    try:
        socket.create_connection(("example.invalid", 443), timeout=0.01)
    except Exception as exc:  # noqa: BLE001 - the guard IS the assertion
        raised = exc
    out("  guard proof : socket.create_connection -> "
        f"{type(raised).__name__ if raised else 'NO REFUSAL'}")

    check("the network layer is hard-blocked in-process",
          isinstance(raised, NetworkBlocked))
    check("hermes is imported from THIS tree (never another checkout)",
          hermes_path.is_relative_to(REPO_ROOT / "src"),
          str(hermes_path.relative_to(REPO_ROOT)))
    check("the clock is frozen at the documented instant",
          CLOCK_OBJ() == CLOCK == CLOCK_OBJ.now_utc(), CLOCK)


# ── BEAT 2: the model plane routes a request (stub backend) ──


class StubModelProvider:
    """A stub ``ModelProvider`` (the backend): declares a profile, serves a
    scripted response, records every call. No vendor, no network, no key."""

    provider_id = "stub"

    def __init__(self, profiles: tuple[ModelProfile, ...],
                 responses: list[ModelResponse]) -> None:
        self._profiles = tuple(profiles)
        self._responses = list(responses)
        self.calls: list[Any] = []

    def describe(self) -> tuple[ModelProfile, ...]:
        return self._profiles

    def invoke(self, call: Any) -> ModelResponse:
        self.calls.append(call)
        if self._responses:
            return self._responses.pop(0)
        return ModelResponse(text="{}")

    def stream(self, call: Any) -> tuple[Any, ...]:
        self.calls.append(call)
        return ()


DIRECTOR_CONTRACT = OutputContract(
    name="director_proposal",
    fields=(FieldSpec("kind", "string"),
            FieldSpec("rationale", "string", required=False)),
    kind_field="kind",
    rationale_field="rationale",
)


def beat_model_plane() -> ModelProposal:
    banner("BEAT 2 - THE MODEL PLANE ROUTES A REQUEST (STUB BACKEND)")
    out("  > config picks the tier -> provider:model; a stub backend answers; "
        "the plane accounts every attempt")
    cite(MODEL_PLANE, 'LOCK = "LOCK"', 186)
    cite(MODEL_PLANE, 'ROLE = "ROLE"', 190)

    profile = ModelProfile(
        provider_id="stub", model_id="m1", context_window_tokens=8000,
        max_output_tokens=1024, supports_structured_output=True,
        input_cost_per_1k_tokens=0.5, output_cost_per_1k_tokens=1.5)
    provider = StubModelProvider((profile,), [ModelResponse(
        text=json.dumps({"kind": "INSERT_TASK", "rationale":
                         "admit a fetch task for the question"}),
        usage=TokenUsage(input_tokens=120, output_tokens=40))])
    router = ModelRouter(
        providers=[provider],
        policy=ModelPlanePolicy(tier_refs={"s": "stub:m1"}, fallback_chain=()),
        clock=CLOCK_OBJ, proposable_kinds=frozenset({"INSERT_TASK", "BRANCH"}),
        tool_allowlist=frozenset(), sleep=CLOCK_OBJ.sleep,
        jitter_source=lambda low, high: 0.0)
    out(f"  registered providers : {router.provider_ids()}")

    result = router.invoke(ModelRequest(
        tier="s", profile="director", lease_generation=LEASE,
        prompt=(UntrustedContent(text=QUESTION, origin="operator.brief",
                                 ref="brief-1"),),
        output_contract=DIRECTOR_CONTRACT))
    if isinstance(result, ModelProposal):
        out(f"  outcome: PROPOSAL from {result.provider_id}/{result.model_id} "
            f"(tier {result.tier})")
        out(f"  structured: {json.dumps(dict(result.structured), sort_keys=True)}")
    else:
        out(f"  outcome: REFUSAL code={result.code} detail={result.detail[:80]}")

    rows = router.accounting()
    for row in rows:
        out(f"  account  seq={row.sequence} attempt={row.attempt} "
            f"outcome={row.outcome} provider={row.provider_id} "
            f"tokens={row.usage.total_tokens} price_usd={row.price_usd}")
    out(f"  totals   usage={router.total_usage().total_tokens} "
        f"price_usd={router.total_price_usd()}")
    router.verify_accounting()
    out("  accounting verified: one row per attempt, no untracked call")

    check("the model plane returns a proposal (not an authority)",
          isinstance(result, ModelProposal))
    check("the proposal's kind is inside the injected proposable allowlist",
          isinstance(result, ModelProposal)
          and result.structured.get("kind") in ("INSERT_TASK", "BRANCH"))
    check("exactly one accounting row, attempt 1, outcome OK",
          len(rows) == 1 and rows[0].attempt == 1 and rows[0].outcome == "OK",
          f"{len(rows)} row(s)")
    check("usage and price are accounted exactly",
          isinstance(result, ModelProposal)
          and router.total_usage().total_tokens == 160
          and router.total_price_usd() == 0.12,
          f"{router.total_usage().total_tokens} tokens / "
          f"{router.total_price_usd()} usd")
    check("no credential field exists anywhere on the call form",
          not any("credential" in name or "api_key" in name
                  for name in getattr(provider.calls[0], "__dataclass_fields__", {})))
    if not isinstance(result, ModelProposal):
        raise RuntimeError("model plane refused the happy-path request")
    return result


# ── BEAT 3: the capability plane invokes (permissioned) ──


def _echo_tool(arguments: dict[str, Any], context: ToolCallContext) -> ToolResult:
    return ToolResult(payload=f"echo:{arguments.get('text', '')}")


def beat_capability_plane() -> Observation:
    banner("BEAT 3 - THE CAPABILITY PLANE INVOKES (PERMISSIONED)")
    out("  > one gated execution path: declare, grant, gate, record an envelope")
    cite(f"{CAP_PLANE}/types.py", 'ROLE = "ROLE"', 104)
    cite(f"{CAP_PLANE}/invoke.py", "class CapabilityInvoker:", 316)

    registry = CapabilityRegistry(allowlist=frozenset({"cap.echo"}))
    registry.register_tool(Tool(
        tool_id="svc.echo", summary="Echo declared text back.",
        inputs=(InputField(name="text", type="string", max_bytes=64),)))
    registry.register_capability(Capability(
        capability_id="cap.echo", tool_id="svc.echo"))
    registry.register_tool_set(ToolSet(
        set_id="set.core", capability_ids=("cap.echo",), summary="core"))

    grant = ToolGrant(grant_id="grant.full", profile="analyst",
                      tool_set_ids=frozenset({"set.core"}),
                      max_risk=RiskLevel.HIGH.value)
    out("  registry enumerates (grant-scoped): "
        f"{list(registry.enumerate(grant=grant).ids())}")
    invoker = CapabilityInvoker(
        registry=registry, implementations={"svc.echo": _echo_tool},
        clock=CLOCK_OBJ, ledger=InMemoryIdempotencyLedger())

    observation = invoker.invoke(InvokeRequest(
        capability_id="cap.echo", arguments={"text": "hello"},
        idempotency_key="idem-1", lease_generation=LEASE, profile="analyst",
        rationale="the brief asks for a bounded echo", grant=grant))
    if isinstance(observation, Observation):
        out(f"  outcome: OBSERVATION status={observation.status} "
            f"replayed={observation.replayed}")
        out(f"  payload : {observation.payload.text if observation.payload else ''}")
        if observation.envelope is not None:
            out(f"  envelope: complete={observation.envelope.is_complete()} "
                f"authority={observation.envelope.authority.decision} "
                f"grant={observation.envelope.authority.grant_id}")
            out(f"  envelope narrative: {observation.envelope.reconstruct()}")
    else:
        out(f"  outcome: REFUSAL code={observation.code}")

    ungranted = invoker.invoke(InvokeRequest(
        capability_id="cap.echo", arguments={"text": "probe"},
        idempotency_key="idem-2", lease_generation=LEASE, profile="analyst",
        rationale="no grant on purpose", grant=None))
    if isinstance(ungranted, CapabilityRefusal):
        out(f"  ungranted caller -> REFUSAL code={ungranted.code} "
            f"detail={ungranted.detail[:70]}")
        out(f"  ungranted envelope authority="
            f"{ungranted.envelope.authority.decision if ungranted.envelope else '?'}")
    else:
        out("  ungranted caller -> ADMITTED (unexpected)")

    check("a permissioned invoke returns a successful observation",
          isinstance(observation, Observation) and observation.ok())
    check("the observation carries a complete who/why/authority envelope",
          isinstance(observation, Observation) and observation.envelope is not None
          and observation.envelope.is_complete())
    check("the envelope records the authority decision GRANTED",
          isinstance(observation, Observation) and observation.envelope is not None
          and observation.envelope.authority.decision == "GRANTED")
    check("an ungranted caller is refused with the ROLE code (refusal-as-data)",
          isinstance(ungranted, CapabilityRefusal) and ungranted.code == "ROLE",
          ungranted.code if isinstance(ungranted, CapabilityRefusal) else "?")
    check("the ungranted refusal's envelope records REFUSED",
          isinstance(ungranted, CapabilityRefusal)
          and ungranted.envelope is not None
          and ungranted.envelope.authority.decision == "REFUSED")
    if not isinstance(observation, Observation):
        raise RuntimeError("capability plane refused the permissioned invoke")
    return observation


# ── BEAT 4: the runtime runs / delegates / checkpoints ──


class ScriptedModel:
    """A ``ModelPort`` stub: serves scripted model outputs, keyed per profile
    (a run's own calls are the profile's; a review/delegation child's are the
    child profile's). No network, no model is asked."""

    def __init__(self, scripts: dict[str, list[Any]]) -> None:
        self._scripts = {name: list(items) for name, items in scripts.items()}
        self.calls: list[Any] = []

    def invoke(self, request: ModelRequest) -> Any:
        self.calls.append(request)
        script = self._scripts.get(request.profile) or self._scripts.get("*")
        if not script:
            return ModelRefusal(code=MALFORMED_PAYLOAD,
                                detail=f"no scripted response for "
                                       f"{request.profile!r}")
        return script.pop(0)


class StubApplier:
    """The Orchestration API stub - using the REAL spine value types.

    Identity is content-addressed exactly as the spine does it, so the same
    intent comes back ``duplicate=True``; that is what makes "resume
    re-emits and the spine dedupes" checkable without a database.
    """

    def __init__(self) -> None:
        self.calls: list[Intent] = []
        self._seen: dict[str, str] = {}

    def __call__(self, intent: Intent) -> IntentResult:
        self.calls.append(intent)
        key = digest_of({"kind": intent.kind.value, "project": intent.project_id,
                         "payload": dict(intent.payload)})
        if key in self._seen:
            return IntentResult(kind=intent.kind, entity_type="task",
                                entity_id=self._seen[key], duplicate=True,
                                row={}, event_type="TaskCreated")
        entity = "task_" + key[:16]
        self._seen[key] = entity
        return IntentResult(kind=intent.kind, entity_type="task",
                            entity_id=entity, duplicate=False,
                            row={}, event_type="TaskCreated")

    def kinds(self) -> tuple[str, ...]:
        return tuple(intent.kind.value for intent in self.calls)


def _scripted(structured: dict[str, Any]) -> ModelProposal:
    return ModelProposal(provider_id="stub", model_id="m1", tier="adversary",
                         profile="scripted", lease_generation=LEASE,
                         structured=dict(structured))


def beat_runtime_plane() -> None:
    banner("BEAT 4 - THE RUNTIME PLANE: RUN -> DELEGATE -> CHECKPOINT")
    out("  > one bounded loop emits intent PROPOSALS; a delegation is a child "
        "task; a checkpoint is resumable")
    cite(f"{RUNTIME_PLANE}/run.py", "class AgentRuntime:", 265)

    applier = StubApplier()
    model = ScriptedModel({
        "critic": [
            _scripted({"kind": "ABANDON", "rationale": "the evidence is weak",
                       "payload": {"why": "single-source"}}),
            _scripted({"kind": "ABANDON", "rationale": "nothing to object to",
                       "payload": {"why": "replication clean"}}),
            _scripted({"kind": "ABANDON", "rationale": "nothing to object to",
                       "payload": {"why": "replication clean"}}),
        ],
        "verifier": [_scripted({"rationale": "delegate the check", "delegations":
                                [{"profile": "critic",
                                  "spec": {"topic": "replication"}}]})],
    })
    runtime = AgentRuntime(
        model=model, orchestration=applier, profiles=load_profiles(),
        checkpoints=InMemoryCheckpointStore(),
        delegations=InMemoryDelegationStore(), clock=CLOCK_OBJ)

    # 4a - run a bounded task.
    ctx = TaskContext(task_id="task-root", project_id=PROJECT_ID,
                      lease_generation=LEASE, limits=RunLimits(max_ticks=1))
    result = runtime.run("critic", ctx)
    out(f"  run: state={result.state} termination={result.termination} "
        f"ticks={result.ticks} proposals={len(result.proposals)}")
    for proposal in result.proposals:
        out(f"  proposal: kind={proposal.intent.kind.value} "
            f"admission={proposal.admission} entity={proposal.admitted_entity_id}")

    # 4b - delegate a child task.
    delegated = runtime.run("verifier", TaskContext(
        task_id="task-verify", project_id=PROJECT_ID, lease_generation=LEASE,
        limits=RunLimits(max_ticks=1)))
    records = runtime.delegation_records(run_id=delegated.run_id)
    for record in records:
        out(f"  delegation: profile={record.profile} state={record.state} "
            f"child_state={record.child_state} "
            f"child_task={record.child_task_id}")
    out(f"  orchestration emitted: {applier.kinds()}")

    # 4c - checkpoint + resume.
    checkpoint = runtime.checkpoint(result.run_id)
    if checkpoint is not None:
        out(f"  checkpoint: run={checkpoint.run_id[:20]}… "
            f"tick={checkpoint.tick} state={checkpoint.state} "
            f"terminal={checkpoint.is_terminal()}")
    resumed = runtime.resume(result.run_id, lease_generation=LEASE)
    if isinstance(resumed, ProposalSet):
        out(f"  resume: state={resumed.state} ticks={resumed.ticks} "
            f"digest_match={resumed.digest() == result.digest()}")
    else:
        out(f"  resume: REFUSAL code={resumed.code}")

    admitted = [p for p in result.proposals if p.admission == Admission.ADMITTED.value]
    check("the runtime returns a ProposalSet (proposals only, no transition)",
          isinstance(result, ProposalSet) and len(result.proposals) >= 1)
    check("the run's proposal was ADMITTED by the injected orchestration API",
          len(admitted) == 1 and bool(admitted[0].admitted_entity_id),
          f"{len(admitted)} admitted")
    check("a delegation is a child task with a DONE derived record",
          len(records) == 1
          and records[0].state == DelegationState.DONE.value
          and records[0].child_state == "SUCCEEDED"
          and bool(records[0].child_task_id),
          f"{records[0].state}/{records[0].child_state}" if records else "no record")
    check("a checkpoint is written for the run",
          checkpoint is not None and checkpoint.run_id == result.run_id)
    check("resume is a terminal no-op with the same digest",
          isinstance(resumed, ProposalSet)
          and resumed.digest() == result.digest())
    check("every runtime proposal carries the lease generation (attribution)",
          all(p.lease_generation == LEASE for p in result.proposals))


# ── BEAT 5: the governance plane checks the result ──


def beat_governance_plane(result: ModelProposal) -> None:
    banner("BEAT 5 - THE GOVERNANCE PLANE CHECKS THE RESULT")
    out("  > before any consequence of the run lands, authority is decided: "
        "agent authority vs a human surface, an operator credential, a bound "
        "decision")
    cite(f"{GOV_PLANE}/authority.py", 'ALLOWED = "ALLOWED"', 216)
    cite(f"{GOV_PLANE}/policy.py", 'ROLE = "ROLE"', 130)

    allowed = evaluate_authority(ActionRequest(
        action=WEB_SEARCH, project_id=PROJECT_ID, actor="RESEARCHER"))
    out(f"  {WEB_SEARCH} by RESEARCHER -> verdict={allowed.verdict} "
        f"required={allowed.required_authority}")

    human_claim = evaluate_authority(ActionRequest(
        action=CONTRADICTION_DECLARE, project_id=PROJECT_ID,
        actor="RESEARCHER", actor_is_human=True))
    out(f"  {CONTRADICTION_DECLARE} claiming a human surface -> "
        f"verdict={human_claim.verdict} code="
        f"{human_claim.refusal.code if human_claim.refusal else '?'} "
        f"requirement={human_claim.requirement}")

    no_credential = evaluate_authority(ActionRequest(
        action=CONTRADICTION_DECLARE, project_id=PROJECT_ID,
        actor="RESEARCHER", operator_id=OP_ID, now=CLOCK))
    out(f"  {CONTRADICTION_DECLARE} with an unratified operator -> "
        f"verdict={no_credential.verdict} code="
        f"{no_credential.refusal.code if no_credential.refusal else '?'} "
        f"requirement={no_credential.requirement}")

    credential = CredentialRow(operator_id=OP_ID, name="Demo Operator",
                               created_at=CLOCK)
    no_decision = evaluate_authority(
        ActionRequest(action=CONTRADICTION_DECLARE, project_id=PROJECT_ID,
                      actor="RESEARCHER", operator_id=OP_ID, now=CLOCK,
                      correlation_id=SCOPE),
        EvidenceContext(credential=credential, decisions=()))
    out(f"  {CONTRADICTION_DECLARE} ratified but with no bound decision -> "
        f"verdict={no_decision.verdict} code="
        f"{no_decision.refusal.code if no_decision.refusal else '?'} "
        f"requirement={no_decision.requirement}")

    out(f"  over the run's result: kind={result.structured.get('kind')} "
        f"-> the consequence still needs a governed action")

    check("an agent-authority action is ALLOWED",
          allowed.verdict == ALLOWED and allowed.refusal is None)
    check("a human-surface claim by an agent is REFUSED (ROLE/AUTHORITY)",
          human_claim.verdict == REFUSED and human_claim.refusal is not None
          and human_claim.refusal.code == "ROLE")
    check("an unratified operator is REFUSED (OPERATOR/CREDENTIAL)",
          no_credential.verdict == REFUSED and no_credential.refusal is not None
          and no_credential.refusal.code == "OPERATOR")
    check("a ratified human action with no bound decision is REFUSED "
          "(PROPOSAL/DECISION)",
          no_decision.verdict == REFUSED and no_decision.refusal is not None
          and no_decision.refusal.code == "PROPOSAL")
    check("the governance plane returns refusals as data (never raises)",
          all(verdict.refusal is not None
              for verdict in (human_claim, no_credential, no_decision)))


# ── BEAT 6: refusals are data ──


def beat_refusals_are_data() -> None:
    banner("BEAT 6 - REFUSALS ARE DATA (EVERY PLANE, THE SAME DISCIPLINE)")
    out("  > a malformed request is refused as a value at each plane's boundary")

    malformed = ModelRequest.from_mapping({
        "tier": "s", "profile": "director", "lease_generation": LEASE,
        "system_prompt": "smuggled"})
    out(f"  model plane   : {malformed.as_dict()['code']} "
        f"({malformed.detail[:48]})" if isinstance(malformed, ModelRefusal)
        else "  model plane   : admitted (unexpected)")

    registry = CapabilityRegistry(allowlist=frozenset({"cap.echo"}))
    registry.register_tool(Tool(tool_id="svc.echo", summary="echo",
                                inputs=(InputField(name="text", type="string"),)))
    registry.register_capability(Capability(capability_id="cap.echo",
                                            tool_id="svc.echo"))
    registry.register_tool_set(ToolSet(set_id="set.core",
                                       capability_ids=("cap.echo",)))
    invoker = CapabilityInvoker(registry=registry,
                                implementations={"svc.echo": _echo_tool},
                                clock=CLOCK_OBJ)
    unknown = invoker.invoke(InvokeRequest(
        capability_id="cap.nope", arguments={}, idempotency_key="idem-x",
        lease_generation=LEASE, profile="analyst", rationale="probe",
        grant=ToolGrant(grant_id="g", profile="analyst",
                        tool_set_ids=frozenset({"set.core"}))))
    out(f"  capability    : {unknown.code} ({unknown.detail[:48]})"
        if isinstance(unknown, CapabilityRefusal) else "  capability    : ok (?)")

    check("the model plane refuses a smuggled request key as data",
          isinstance(malformed, ModelRefusal) and malformed.code == MALFORMED_PAYLOAD)
    check("the capability plane refuses an unknown capability as data",
          isinstance(unknown, CapabilityRefusal)
          and unknown.code in ("MALFORMED_PAYLOAD", "ROLE"))


# ── digest + main ──

# Everything volatile about a run, masked before hashing.
_VOLATILE = (
    (re.compile(r"\d+\.\d+s"), "<elapsed>"),
    (re.compile(r"[Tt][Ee][Mm][Pp][\\/][A-Za-z0-9_.-]+"), "<tmp-seg>"),
    (re.compile(r"pytest-\d+"), "pytest-N"),
    (re.compile(r"ALIZOG~1", re.I), "<user>"),
)


def replay_digest() -> str:
    masked = []
    for line in EPISODE:
        text = line
        for pattern, replacement in _VOLATILE:
            text = pattern.sub(replacement, text)
        masked.append(text)
    blob = "\n".join(masked).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


def main() -> int:
    started = time.perf_counter()
    mutation = os.environ.get("DEMO_PLATFORM_MUTATION", "").strip().lower()
    try:
        beat_frame()
        model_result = beat_model_plane()
        beat_capability_plane()
        beat_runtime_plane()
        beat_governance_plane(model_result)
        beat_refusals_are_data()
        if mutation == "raise":
            raise RuntimeError("DEMO_PLATFORM_MUTATION=raise: injected fault "
                               "(proves the exit-2 contract)")
        if mutation == "check":
            check("injected failing check (DEMO_PLATFORM_MUTATION=check)",
                  False, "proves the exit-1 contract")
    except Exception:  # noqa: BLE001 - the demo body must never swallow
        out()
        out("DEMO RAISED - the traceback is printed, never swallowed:")
        out(traceback.format_exc())
        out()
        out("EXIT 2")
        return 2

    elapsed = time.perf_counter() - started
    banner("CITATIONS (every oracle line this run read, proven)")
    for citation in CITATIONS:
        out(f"  {citation}")
    files = {citation.rsplit(":", 1)[0] for citation in CITATIONS}
    check(f"{len(CITATIONS)} repo citations verified across {len(files)} file(s)",
          len(CITATIONS) >= 6 and len(files) >= 3,
          f"{len(CITATIONS)} citations / {len(files)} files")
    check(f"the whole demo ran inside the budget ({elapsed:.2f}s)",
          elapsed < BUDGET_SECONDS, f"{elapsed:.2f}s")

    digest = replay_digest()
    total = len(CHECKS)
    good = passed()
    banner("RESULT")
    out(f"  checks: {good}/{total} passed")
    out(f"  REPLAY DIGEST: {digest}")
    out("  (two consecutive runs must print the same digest)")
    out(f"RESULT: {good}/{total} checks passed in {elapsed:.2f}s")
    failed = [label for label, ok, _ in CHECKS if not ok]
    if failed:
        out("FAILED: " + "; ".join(failed))
        out("EXIT 1")
        return 1
    out("EXIT 0")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
