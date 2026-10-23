"""LOOP-0 triage probe — E1 re-derived on current main (characterisation only).

Written for the LOOP-0 triage of the external loop-engineering audit. The
external probe was scoped to ``audit/r1-manifest@1918dad``; this file re-derives
the E1 prediction against the *current* tree from scratch, with its own fakes.
It drives both reachable methodology paths:

1. the live composition path — ``RuntimeWiring`` + the W3 driver
   (``hermes.research.task_handlers.methodology_driver``), which is what the
   controller's W4 call site dispatches; and
2. the methodology plane's own driver (``hermes.methodology.workflows``), which
   remains the swap-probe/test path.

Copied from ``audit/loop-0-triage@a481f3f`` and **inverted by LOOP-1** to pin
the fixed behaviour (the pre-fix characterisation stays on that branch as the
record). What is asserted now:

* a stage run's prompt carries ``runtime.payload`` envelopes — the methodology
  id and every stage name reach the model as content (E1);
* a review child's prompt carries ``runtime.review`` envelopes — the drafts
  themselves, never a bare digest of the delegation spec (E1/G4);
* E4 is a characterisation pin: proposals are admitted before their sibling
  tool batch; a sibling tool failure does not retract them.

If this regresses, fix the behaviour — do not weaken these assertions, and do
not delete the file (the audit branch keeps the before picture).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from hermes.agents.runtime.assembly import PAYLOAD_ORIGIN, PROPOSAL_ORIGIN
from hermes.agents.runtime.config import load_profiles, parse_profile
from hermes.agents.runtime.run import run as runtime_run
from hermes.agents.runtime.types import TaskContext
from hermes.agents.runtime.wiring import RuntimeWiring
from hermes.core.intents import IntentKind
from hermes.core.task_status import TaskStatus
from hermes.methodology.workflows import (
    LITERATURE_REVIEW_DOCUMENT,
    MethodologyInputs,
    MethodologyRun,
    parse_methodology,
)
from hermes.methodology.workflows import (
    run_methodology as plane_run_methodology,
)
from hermes.research.task_handlers.methodology_driver import (
    MethodologyExecution,
)
from hermes.research.task_handlers.methodology_driver import (
    run_methodology as driver_run_methodology,
)
from hermes.tools.capabilities.types import CapabilityRefusal, InvokeRequest
from hermes.tools.models.router import ModelProposal, ModelRequest

PROJECT = "p-loop0"
TASK = "task-loop0"
LEASE = "lease-loop0"
QUESTION = "does the payload reach the model?"

#: The citation refs a grounded run cites, all registered in-project (same shape
#: the W3 suite uses; the driver has no opinion about their values).
REFS: dict[str, str] = {
    "HYPOTHESIS": "hypothesis:program-loop0/h1",
    "PREDICTION": "prediction:program-loop0/h1/p1",
    "EVIDENCE": "evidence:evidence-loop0/e1",
    "CLAIM": "claim:claim-loop0/c1",
}

_TICK = re.compile(r"\Atick \d+ of \d+\Z")
_HEX64 = re.compile(r"\A[0-9a-f]{64}\Z")

#: Profiles whose shipped authority admits an ordinary `INSERT_TASK` draft.
#: The scripted model proposes one there and stays silent everywhere else, so
#: every run is deterministic and every review child is exercised.
_PROPOSING_PROFILES = frozenset(
    {"planner", "researcher", "experimenter", "synthesizer"})


# ═══════════════════════ fakes ═══════════════════════


class RecordingModel:
    """A `ModelPort` that records every request and proposes on demand."""

    def __init__(self) -> None:
        self.calls: list[ModelRequest] = []

    def invoke(self, request: ModelRequest) -> ModelProposal:
        self.calls.append(request)
        structured: dict[str, Any] = {}
        if request.profile in _PROPOSING_PROFILES:
            structured = {
                "kind": "INSERT_TASK",
                "rationale": "loop-0 probe draft",
                "payload": {"goal": "loop-0 probe"},
            }
        return ModelProposal(
            provider_id="scripted", model_id="scripted", tier="research",
            profile=request.profile, lease_generation=request.lease_generation,
            structured=structured)


@dataclass(frozen=True, slots=True)
class _Applied:
    """The shape `run._apply` reads off an injected Orchestration API result."""

    entity_id: str
    duplicate: bool


class RecordingApplier:
    """The spine's injection point as a recording double (`apply_intent` seam)."""

    def __init__(self) -> None:
        self.calls: list[Any] = []

    def __call__(self, intent: Any) -> _Applied:
        self.calls.append(intent)
        return _Applied(entity_id=f"ent_{len(self.calls):04d}", duplicate=False)


class ProposingToolModel:
    """Proposes one `INSERT_TASK` *and* asks for one capability call."""

    def __init__(self) -> None:
        self.calls: list[ModelRequest] = []

    def invoke(self, request: ModelRequest) -> ModelProposal:
        self.calls.append(request)
        return ModelProposal(
            provider_id="scripted", model_id="scripted", tier="research",
            profile=request.profile, lease_generation=request.lease_generation,
            structured={
                "proposals": [{"kind": "INSERT_TASK",
                               "rationale": "draft emitted before the tool batch",
                               "payload": {"goal": "e4 probe"}}],
                "tool_calls": [{"capability_id": "probe_tool",
                                "arguments": {}, "rationale": "e4 probe"}],
            })


class FailingCapability:
    """A capability port that refuses: the tool batch fails after the draft."""

    def invoke(self, request: InvokeRequest) -> CapabilityRefusal:
        return CapabilityRefusal(
            code="ROLE", detail="probe: the tool fails after the draft crossed",
            capability_id=request.capability_id, profile=request.profile)


def _e4_profile():
    return parse_profile({
        "name": "e4-probe",
        "role": "e4 probe profile",
        "agent_profile": "RESEARCHER",
        "model_policy": {"tier": "research",
                         "structured_fields": ["proposals", "tool_calls"],
                         "allows_tool_calls": True},
        "tools": ["probe_tool"],
        "authority": {"proposable_kinds": ["INSERT_TASK"]},
        "termination": {"max_ticks": 1, "max_proposals": 5,
                        "stop_when": "proposals_raised"},
    }, source="e4-probe")


class ContextRecordingWiring:
    """Delegates to a real `RuntimeWiring` and records each stage's context.

    `project_stage` puts the stage payload on the `TaskContext` the driver hands
    the runtime; this wrapper captures exactly those contexts so the probe can
    show that the payload exists and still never reaches a prompt.
    """

    def __init__(self, inner: RuntimeWiring) -> None:
        self._inner = inner
        self.contexts: list[Any] = []

    @property
    def lease_generation(self) -> str:
        return self._inner.lease_generation

    def run(self, profile: Any, task_context: Any, *,
            token: Any = None) -> Any:
        self.contexts.append(task_context)
        return self._inner.run(profile, task_context, token=token)


def _inputs(question: str = QUESTION) -> MethodologyInputs:
    return MethodologyInputs(
        question=question,
        external_refs=dict(REFS),
        admission_refs=tuple(REFS.values()),
        retracted_refs=())


def _prompt_texts(request: ModelRequest) -> list[str]:
    return [item.text for item in request.prompt]


def _report(title: str, model: RecordingModel) -> None:
    print(f"[LOOP-0 probe] {title}: {len(model.calls)} model call(s)")
    for index, request in enumerate(model.calls):
        origins = [item.origin for item in request.prompt]
        print(f"  call {index}: profile={request.profile} "
              f"origins={origins} texts={_prompt_texts(request)!r}")


# ═══════════════════════ 1. the live composition path ═══════════════════════


def test_driver_path_prompts_carry_the_payload_and_the_review_drafts() -> None:
    model = RecordingModel()
    applier = RecordingApplier()
    wiring = ContextRecordingWiring(RuntimeWiring(
        model=model, orchestration=applier, lease_generation=LEASE,
        profiles=load_profiles()))
    outcome = driver_run_methodology(
        parse_methodology(dict(LITERATURE_REVIEW_DOCUMENT)), _inputs(),
        wiring=wiring, project_id=PROJECT, task_id=TASK)
    _report("driver path (RuntimeWiring + W3 driver)", model)

    assert isinstance(outcome, MethodologyExecution)
    assert outcome.termination == "COMPLETE"
    assert len(outcome.stages) == 9
    assert wiring.contexts, "no stage context reached the runtime"

    # LOOP-1: the payload the run *carries* is what the model now reads — the
    # methodology id and every stage identity reach the prompt as content.
    stage_calls = [request for request in model.calls
                   if not any(item.origin == PROPOSAL_ORIGIN
                              for item in request.prompt)]
    review_calls = [request for request in model.calls
                    if any(item.origin == PROPOSAL_ORIGIN
                           for item in request.prompt)]
    for request in stage_calls:
        assert any(item.origin == PAYLOAD_ORIGIN for item in request.prompt)
        assert any(_TICK.match(item.text) for item in request.prompt)
    joined_stage = "\n".join(text for request in stage_calls
                             for text in _prompt_texts(request))
    assert "literature-review" in joined_stage
    for context in wiring.contexts:
        assert context.payload["stage"] in joined_stage

    # The review child carries the drafts themselves — no bare spec digest.
    assert review_calls, "no review child ran"
    for request in review_calls:
        assert any(item.origin == PROPOSAL_ORIGIN for item in request.prompt)
        assert not any(_HEX64.match(item.text) for item in request.prompt)
    joined_review = "\n".join(text for request in review_calls
                              for text in _prompt_texts(request))
    assert "loop-0 probe draft" in joined_review


# ═══════════════════════ 2. the methodology plane's own driver ═════════════


def test_plane_path_prompts_carry_the_payload_and_the_review_drafts() -> None:
    model = RecordingModel()
    applier = RecordingApplier()
    outcome = plane_run_methodology(
        parse_methodology(dict(LITERATURE_REVIEW_DOCUMENT)), PROJECT, TASK,
        LEASE, _inputs(),
        model=model, orchestration=applier, profiles=load_profiles())
    _report("plane path (methodology.workflows)", model)

    assert isinstance(outcome, MethodologyRun)
    assert outcome.termination == "COMPLETE"
    assert model.calls, "no model call was made"
    # The plane path renders payloads and review drafts exactly like the live
    # path does (both go through the runtime's default assembler).
    stage_calls = [request for request in model.calls
                   if not any(item.origin == PROPOSAL_ORIGIN
                              for item in request.prompt)]
    review_calls = [request for request in model.calls
                    if any(item.origin == PROPOSAL_ORIGIN
                           for item in request.prompt)]
    assert stage_calls, "no stage run was made"
    for request in stage_calls:
        assert any(item.origin == PAYLOAD_ORIGIN for item in request.prompt)
    joined_stage = "\n".join(text for request in stage_calls
                             for text in _prompt_texts(request))
    assert "literature-review" in joined_stage
    assert review_calls, "no review child ran"
    for request in review_calls:
        assert any(item.origin == PROPOSAL_ORIGIN for item in request.prompt)
        assert not any(_HEX64.match(item.text) for item in request.prompt)


# ═══════════════ 3. E4 — proposals are admitted before their siblings ═══════


def test_proposals_are_admitted_before_the_sibling_tool_batch() -> None:
    """Characterisation pin: a proposal is admitted before its sibling tools.

    The tick's drafts and tool calls come from one model response. The drafts
    are validated and admitted first; the tool batch then runs. This is the
    documented ordering, not a defect: a tick-N proposal is justified by
    evidence from ticks 1..N-1, a tool cannot consume a same-tick admission,
    and a sibling tool failure does not retract the admitted proposal. If the
    ordering ever changes, this pin is what notices.
    """
    model = ProposingToolModel()
    applier = RecordingApplier()
    context = TaskContext(task_id="task-e4", project_id=PROJECT,
                          lease_generation=LEASE)
    result = runtime_run("e4-probe", context, model=model,
                         orchestration=applier,
                         capabilities=FailingCapability(),
                         profiles={"e4-probe": _e4_profile()})
    print(f"[LOOP-0 probe] E4 (documented ordering): state={result.state} "
          f"termination={result.termination} "
          f"applier_calls={len(applier.calls)}")

    assert result.state == TaskStatus.FAILED.value
    assert result.termination == "TOOL_FAILED"
    assert len(applier.calls) == 1, \
        "the documented ordering changed: the draft was not admitted first"
    assert applier.calls[0].kind is IntentKind.INSERT_TASK
    assert [item.intent.kind.value for item in result.proposals] == ["INSERT_TASK"]
