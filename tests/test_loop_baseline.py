"""LOOP-M baseline — scripted scenarios, pinned metrics, determinism.

The corpus is deliberately tiny and fully scripted: a declared profile, a
scripted model, scripted capability results, and a frozen clock. It measures
the loop's mechanics on a fixed model layer, not an LLM's research quality.
Nothing here imports or edits ``hermes.agents.runtime``; every fact is read
from the runtime's public run surface (``ProposalSet``, checkpoint, trace) and
from the two test-owned ports.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta
from typing import Any, Mapping

from hermes.agents.runtime.config import (
    AuthoritySpec,
    ModelPolicySpec,
    ProfileSpec,
    ReviewSpec,
    TerminationSpec,
)
from hermes.agents.runtime.run import AgentRuntime
from hermes.agents.runtime.types import (
    RunLimits,
    TaskContext,
    digest_of,
)
from hermes.eval.loop_metrics import (
    PromptCall,
    RunObservation,
    ScenarioObservation,
    ToolCall,
    aggregate_metrics,
)
from hermes.research.gateway import IntentResult
from hermes.security.boundaries import UntrustedContent
from hermes.tools.capabilities.types import FailureKind, Observation
from hermes.tools.models.router import ModelProposal

# ═══════════════════════ corpus ═══════════════════════

_NO_REVIEW = {"reviewer_profile": "", "required": False,
              "max_review_rounds": 1}


def _parent(*, tools: tuple[str, ...] = (),
            structured: tuple[str, ...] = ("proposals", "tool_calls"),
            stop_when: str = "proposals_raised", max_ticks: int = 1,
            review: Mapping[str, Any] | None = None,
            deadline: float | None = None) -> dict[str, Any]:
    return {
        "name": "researcher",
        "agent_profile": "RESEARCHER",
        "tools": list(tools),
        "kinds": ["INSERT_TASK"],
        "structured": list(structured),
        "stop_when": stop_when,
        "max_ticks": max_ticks,
        "max_proposals": 6,
        "max_tool_calls": 4,
        "deadline": deadline,
        "review": dict(review or _NO_REVIEW),
    }


def _critic() -> dict[str, Any]:
    return {
        "name": "critic",
        "agent_profile": "ADVERSARY",
        "tools": [],
        "kinds": ["ABANDON"],
        "structured": ["proposals"],
        "stop_when": "no_proposals",
        "max_ticks": 1,
        "max_proposals": 4,
        "max_tool_calls": 4,
        "deadline": 30.0,
        "review": dict(_NO_REVIEW),
    }


def _worker() -> dict[str, Any]:
    return {
        "name": "worker",
        "agent_profile": "RESEARCHER",
        "tools": [],
        "kinds": ["INSERT_TASK"],
        "structured": ["proposals"],
        "stop_when": "proposals_raised",
        "max_ticks": 1,
        "max_proposals": 4,
        "max_tool_calls": 4,
        "deadline": 30.0,
        "review": dict(_NO_REVIEW),
    }


def _context(scenario: str, *, stage: str, methodology: str,
             predecessor: str) -> dict[str, Any]:
    return {
        "task_id": f"task-{scenario}",
        "project_id": "loop-baseline",
        "lease_generation": "gen-1",
        "iteration": 1,
        "context_texts": [
            f"{scenario} stage brief: {stage}",
            f"{scenario} methodology: {methodology}",
        ],
        "payload": {
            "stage": stage,
            "methodology": methodology,
            "predecessor": predecessor,
        },
        "limits": {
            "max_ticks": 0,
            "max_proposals": 0,
            "max_tool_calls": 0,
            "deadline_seconds": None,
            "max_delegation_depth": 1,
            "allow_child_runs": True,
            "max_child_runs": 4,
        },
    }


def _evidence(text: str, artifact: str) -> dict[str, Any]:
    return {"status": "OK", "payload": text, "artifacts": [artifact]}


_TWO_ROUND_REVIEW = {"reviewer_profile": "critic", "required": True,
                     "max_review_rounds": 2}

SCENARIOS: tuple[dict[str, Any], ...] = (
    {
        "id": "S1",
        "root_profile": "researcher",
        "description": "one tick, one proposal, one tool, evidence returns",
        "profiles": {"researcher": _parent(tools=("source_search",))},
        "model": {"researcher": [{
            "kind": "INSERT_TASK", "rationale": "S1 draft",
            "payload": {"spec": {"stage": "S1"}},
            "tool_calls": [{"capability_id": "source_search",
                            "arguments": {"query": "s1"},
                            "rationale": "gather S1"}],
        }]},
        "tools": [_evidence("S1 evidence body", "artifact:S1:evidence")],
        "context": _context(
            "S1", stage="happy path", methodology="one declared tool call",
            predecessor="none"),
        "advance_first_call": 0.0,
    },
    {
        "id": "S2",
        "root_profile": "researcher",
        "description": "multi-tick evidence gathering until stability",
        "profiles": {"researcher": _parent(
            tools=("source_search",), stop_when="converged", max_ticks=3)},
        "model": {"researcher": [
            {"kind": "INSERT_TASK", "rationale": "S2 draft a",
             "payload": {"spec": {"stage": "S2", "step": "a"}},
             "tool_calls": [{"capability_id": "source_search",
                             "arguments": {"query": "alpha"},
                             "rationale": "gather alpha"}]},
            {"kind": "INSERT_TASK", "rationale": "S2 draft b",
             "payload": {"spec": {"stage": "S2", "step": "b"}},
             "tool_calls": [{"capability_id": "source_search",
                             "arguments": {"query": "beta"},
                             "rationale": "gather beta"}]},
        ]},
        "tools": [
            _evidence("S2 stable evidence", "artifact:S2:evidence"),
            _evidence("S2 stable evidence", "artifact:S2:evidence"),
        ],
        "context": _context(
            "S2", stage="convergence", methodology="two observed ticks",
            predecessor="S1"),
        "advance_first_call": 0.0,
    },
    {
        "id": "S3",
        "root_profile": "researcher",
        "description": "same tool and args twice, no new evidence",
        "profiles": {"researcher": _parent(
            tools=("source_search",), stop_when="converged", max_ticks=3)},
        "model": {"researcher": [
            {"kind": "INSERT_TASK", "rationale": "S3 repeated draft",
             "payload": {"spec": {"stage": "S3"}},
             "tool_calls": [{"capability_id": "source_search",
                             "arguments": {"query": "gamma"},
                             "rationale": "gather gamma"}]},
            {"kind": "INSERT_TASK", "rationale": "S3 repeated draft",
             "payload": {"spec": {"stage": "S3"}},
             "tool_calls": [{"capability_id": "source_search",
                             "arguments": {"query": "gamma"},
                             "rationale": "gather gamma"}]},
        ]},
        "tools": [
            _evidence("S3 stable evidence", "artifact:S3:evidence"),
            _evidence("S3 stable evidence", "artifact:S3:evidence"),
        ],
        "context": _context(
            "S3", stage="repeat", methodology="same call twice",
            predecessor="S2"),
        "advance_first_call": 0.0,
    },
    {
        "id": "S4",
        "root_profile": "researcher",
        "description": "review rejects, re-draft passes inside the cap",
        "profiles": {
            "researcher": _parent(
                tools=(), structured=("proposals",),
                stop_when="proposals_raised", max_ticks=2,
                review=_TWO_ROUND_REVIEW),
            "critic": _critic(),
        },
        "model": {
            "researcher": [
                {"kind": "INSERT_TASK", "rationale": "S4 round 1 draft",
                 "payload": {"spec": {"stage": "S4", "round": 1}}},
                {"kind": "INSERT_TASK", "rationale": "S4 round 2 draft",
                 "payload": {"spec": {"stage": "S4", "round": 2}}},
            ],
            "critic": [
                {"kind": "ABANDON", "rationale": "S4 round 1 objection",
                 "payload": {"round": 1}},
                {},
            ],
        },
        "tools": [],
        "context": _context(
            "S4", stage="review recover", methodology="two rounds, one pass",
            predecessor="S3"),
        "advance_first_call": 0.0,
    },
    {
        "id": "S5",
        "root_profile": "researcher",
        "description": "review rejects until the cap",
        "profiles": {
            "researcher": _parent(
                tools=(), structured=("proposals",),
                stop_when="proposals_raised", max_ticks=2,
                review=_TWO_ROUND_REVIEW),
            "critic": _critic(),
        },
        "model": {
            "researcher": [
                {"kind": "INSERT_TASK", "rationale": "S5 round 1 draft",
                 "payload": {"spec": {"stage": "S5", "round": 1}}},
                {"kind": "INSERT_TASK", "rationale": "S5 round 2 draft",
                 "payload": {"spec": {"stage": "S5", "round": 2}}},
            ],
            "critic": [
                {"kind": "ABANDON", "rationale": "S5 round 1 objection",
                 "payload": {"round": 1}},
                {"kind": "ABANDON", "rationale": "S5 round 2 objection",
                 "payload": {"round": 2}},
            ],
        },
        "tools": [],
        "context": _context(
            "S5", stage="review cap", methodology="two rounds, no pass",
            predecessor="S4"),
        "advance_first_call": 0.0,
    },
    {
        "id": "S6",
        "root_profile": "researcher",
        "description": "tool failure after drafts exist (LOOP-5 baseline)",
        "profiles": {"researcher": _parent(tools=("source_search",))},
        "model": {"researcher": [{
            "kind": "INSERT_TASK", "rationale": "S6 draft before failure",
            "payload": {"spec": {"stage": "S6"}},
            "tool_calls": [{"capability_id": "source_search",
                            "arguments": {"query": "fail"},
                            "rationale": "gather then fail"}],
        }]},
        "tools": [{"status": "FAILED", "failure": "TOOL_ERROR",
                   "detail": "scripted tool failure"}],
        "context": _context(
            "S6", stage="tool failure", methodology="one failing tool",
            predecessor="S5"),
        "advance_first_call": 0.0,
    },
    {
        "id": "S7",
        "root_profile": "researcher",
        "description": "deadline expires mid-tick",
        "profiles": {"researcher": _parent(
            tools=(), structured=("proposals",), deadline=10.0)},
        "model": {"researcher": [{
            "kind": "INSERT_TASK", "rationale": "S7 draft before timeout",
            "payload": {"spec": {"stage": "S7"}},
        }]},
        "tools": [],
        "context": _context(
            "S7", stage="deadline", methodology="clock advances mid-call",
            predecessor="S6"),
        "advance_first_call": 11.0,
    },
    {
        "id": "S8",
        "root_profile": "researcher",
        "description": "delegation to a child run",
        "profiles": {
            "researcher": _parent(
                tools=(), structured=("proposals", "delegations"),
                stop_when="proposals_raised", max_ticks=1),
            "worker": _worker(),
        },
        "model": {
            "researcher": [{"delegations": [{
                "profile": "worker",
                "spec": {"stage": "S8-child"},
                "task_type": "AGENT_TASK",
            }]}],
            "worker": [{"kind": "INSERT_TASK",
                        "rationale": "S8 child draft",
                        "payload": {"spec": {"stage": "S8-child"}}}],
        },
        "tools": [],
        "context": _context(
            "S8", stage="delegation", methodology="one child run",
            predecessor="S7"),
        "advance_first_call": 0.0,
    },
)


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False)


def scenario_digest(spec: Mapping[str, Any]) -> str:
    """SHA-256 of one scenario's committed inputs."""
    return hashlib.sha256(_canonical(spec).encode("utf-8")).hexdigest()


def corpus_digest() -> str:
    """SHA-256 of the whole committed scenario corpus."""
    return hashlib.sha256(_canonical(SCENARIOS).encode("utf-8")).hexdigest()


# ═══════════════════════ test-owned ports ═══════════════════════


class _Clock:
    """Frozen callable clock with a monotonic channel and the router protocol."""

    def __init__(self) -> None:
        self._moment = datetime.fromisoformat(
            "2026-01-01T00:00:00.000000+00:00")
        self._monotonic = 0.0

    def __call__(self) -> str:
        return self._moment.isoformat(timespec="microseconds")

    def now_utc(self) -> str:
        return self()

    def monotonic(self) -> float:
        return self._monotonic

    def advance(self, seconds: float) -> None:
        self._moment = self._moment + timedelta(seconds=seconds)
        self._monotonic += seconds


class _ScriptedModel:
    """Serve one structured output per profile, in order; record every request."""

    def __init__(self, scripts: Mapping[str, list[dict[str, Any]]],
                 *, clock: _Clock, advance_first_call: float) -> None:
        self._scripts = {name: [dict(item) for item in items]
                         for name, items in scripts.items()}
        self._clock = clock
        self._advance = advance_first_call
        self.calls: list[Any] = []

    def invoke(self, request: Any) -> ModelProposal:
        self.calls.append(request)
        if self._advance and len(self.calls) == 1:
            self._clock.advance(self._advance)
        script = self._scripts.get(request.profile)
        if not script:
            raise AssertionError(
                f"unexpected model call for profile {request.profile!r}")
        item = script.pop(0)
        return ModelProposal(
            provider_id="scripted", model_id="loop-m", tier=request.tier,
            profile=request.profile,
            lease_generation=request.lease_generation,
            structured=dict(item))

    def assert_consumed(self) -> None:
        leftover = {name: items for name, items in self._scripts.items()
                    if items}
        if leftover:
            raise AssertionError(f"unconsumed model scripts: {leftover!r}")


class _ScriptedCapabilities:
    """Return one scripted observation per actual invocation; record the call."""

    def __init__(self, responses: list[dict[str, Any]]) -> None:
        self._responses = [dict(item) for item in responses]
        self.calls: list[ToolCall] = []

    def invoke(self, request: Any) -> Observation:
        self.calls.append(ToolCall(
            capability_id=request.capability_id,
            arguments_digest=digest_of(dict(request.arguments))))
        if not self._responses:
            raise AssertionError(
                f"unexpected capability call {request.capability_id!r}")
        item = self._responses.pop(0)
        status = str(item.get("status", "OK"))
        if status != "OK":
            return Observation(
                capability_id=request.capability_id,
                status=status,
                failure=FailureKind(str(item["failure"])),
                detail=str(item.get("detail", "")),
                idempotency_key=request.idempotency_key)
        payload = str(item.get("payload", ""))
        return Observation(
            capability_id=request.capability_id,
            status="OK",
            payload=UntrustedContent(
                text=payload, origin="scripted.tool",
                ref=f"tool:{request.capability_id}"),
            artifacts=tuple(str(a) for a in item.get("artifacts") or ()),
            idempotency_key=request.idempotency_key)

    def assert_consumed(self) -> None:
        if self._responses:
            raise AssertionError(
                f"unconsumed tool responses: {self._responses!r}")


class _RecordingApplier:
    """Deterministic Orchestration API stand-in: content-addressed admissions."""

    def __init__(self) -> None:
        self.calls: list[Any] = []
        self._seen: dict[str, str] = {}

    def __call__(self, intent: Any) -> IntentResult:
        self.calls.append(intent)
        key = digest_of({"kind": intent.kind.value,
                         "project": intent.project_id,
                         "payload": dict(intent.payload)})
        if key in self._seen:
            return IntentResult(
                kind=intent.kind, entity_type="task",
                entity_id=self._seen[key], duplicate=True, row={},
                event_type="TaskCreated")
        entity = "task_" + key[:16]
        self._seen[key] = entity
        return IntentResult(
            kind=intent.kind, entity_type="task", entity_id=entity,
            duplicate=False, row={}, event_type="TaskCreated")


# ═══════════════════════ build + measure ═══════════════════════


def _as_profile(spec: Mapping[str, Any]) -> ProfileSpec:
    review = spec["review"]
    return ProfileSpec(
        name=str(spec["name"]),
        role=f"scripted {spec['name']}",
        agent_profile=str(spec["agent_profile"]),
        model_policy=ModelPolicySpec(
            tier="research",
            structured_fields=tuple(spec["structured"]),
            allows_tool_calls=bool(spec["tools"]),
            max_output_tokens=2048),
        tools=tuple(spec["tools"]),
        authority=AuthoritySpec(
            proposable_kinds=tuple(spec["kinds"]),
            director_only=False,
            allowed_capabilities=tuple(spec["tools"])),
        schemas={},
        termination=TerminationSpec(
            max_ticks=int(spec["max_ticks"]),
            max_proposals=int(spec["max_proposals"]),
            stop_when=str(spec["stop_when"]),
            max_model_calls_per_tick=1,
            max_tool_calls=int(spec["max_tool_calls"]),
            deadline_seconds=spec["deadline"]),
        review=ReviewSpec(
            reviewer_profile=str(review["reviewer_profile"]),
            required=bool(review["required"]),
            max_review_rounds=int(review["max_review_rounds"])),
    )


def _prompt_call(request: Any) -> PromptCall:
    payload = 0
    marker = 0
    for part in request.prompt:
        text_bytes = len(part.text.encode("utf-8"))
        if part.origin == "runtime.tick":
            marker += text_bytes
        else:
            payload += text_bytes
        marker += len(part.origin.encode("utf-8"))
        marker += len(str(part.ref).encode("utf-8"))
    return PromptCall(payload_bytes=payload, marker_bytes=marker,
                      total_bytes=payload + marker)


def _tick_new_evidence(feedback: tuple[Any, ...], ticks: int) -> tuple[int, ...]:
    seen: set[str] = set()
    fresh: list[int] = []
    for tick in range(1, ticks + 1):
        tick_digests = {record.evidence_digest() for record in feedback
                        if record.tick == tick}
        fresh.append(len(tick_digests - seen))
        seen.update(tick_digests)
    return tuple(fresh)


def _run_observation(runtime: AgentRuntime, result: Any, checkpoint: Any, *,
                     is_root: bool, profiles: Mapping[str, ProfileSpec]
                     ) -> RunObservation:
    if is_root:
        proposals = result.proposals
        refusals = result.refusals
        verdicts = result.review_verdicts
        ticks = result.ticks
        state = result.state
        termination = result.termination
        profile_name = result.profile
        run_id = result.run_id
    else:
        proposals = checkpoint.proposals
        refusals = checkpoint.refusals
        verdicts = checkpoint.review_verdicts
        ticks = checkpoint.tick
        state = checkpoint.state
        termination = checkpoint.termination
        profile_name = checkpoint.profile
        run_id = checkpoint.run_id
    admitted = sum(1 for p in proposals if p.admission == "ADMITTED")
    duplicate = sum(1 for p in proposals if p.admission == "DUPLICATE")
    intent_refused = sum(1 for p in proposals if p.admission == "REFUSED")
    other_refusals = max(0, len(refusals) - intent_refused)
    profile = profiles[profile_name]
    review_cap = (profile.review.max_review_rounds
                  if profile.review.required else 0)
    return RunObservation(
        run_id=run_id,
        profile=profile_name,
        is_root=is_root,
        state=state,
        termination=termination,
        ticks=ticks,
        trace_digest=runtime.supervisor.trace_digest(run_id),
        admitted=admitted,
        duplicate=duplicate,
        intent_refused=intent_refused,
        other_refusals=other_refusals,
        review_rounds=len(verdicts),
        review_cap=review_cap,
        review_verdicts=tuple("PASS" if v.passed else "FAIL"
                              for v in verdicts),
        tick_new_evidence=_tick_new_evidence(checkpoint.feedback, ticks),
    )


def run_scenario(spec: Mapping[str, Any]) -> ScenarioObservation:
    """Build and run one scenario; return only externally-readable facts."""
    profiles = {name: _as_profile(item)
                for name, item in spec["profiles"].items()}
    clock = _Clock()
    model = _ScriptedModel(
        spec["model"], clock=clock,
        advance_first_call=float(spec["advance_first_call"]))
    capabilities = _ScriptedCapabilities(spec["tools"])
    applier = _RecordingApplier()
    runtime = AgentRuntime(
        model=model, orchestration=applier, capabilities=capabilities,
        profiles=profiles, clock=clock, monotonic=clock.monotonic)
    context = spec["context"]
    task_context = TaskContext(
        task_id=str(context["task_id"]),
        project_id=str(context["project_id"]),
        lease_generation=str(context["lease_generation"]),
        iteration=int(context["iteration"]),
        context=tuple(
            UntrustedContent(
                text=str(text), origin="scenario.context",
                ref=f"{context['task_id']}:{index}")
            for index, text in enumerate(context["context_texts"])),
        payload=dict(context["payload"]),
        limits=RunLimits(**context["limits"]))
    result = runtime.run(str(spec["root_profile"]), task_context)
    root_checkpoint = runtime.checkpoint(result.run_id)
    if root_checkpoint is None:
        raise AssertionError(f"no checkpoint for root {result.run_id!r}")
    runs = [_run_observation(runtime, result, root_checkpoint, is_root=True,
                             profiles=profiles)]
    child_ids: list[str] = []
    for record in result.delegations:
        child_run_id = record.child_run_id
        if not child_run_id or child_run_id in child_ids:
            continue
        child_ids.append(child_run_id)
        child_checkpoint = runtime.checkpoint(child_run_id)
        if child_checkpoint is None:
            raise AssertionError(
                f"no checkpoint for child {child_run_id!r}")
        runs.append(_run_observation(
            runtime, None, child_checkpoint, is_root=False,
            profiles=profiles))
    model.assert_consumed()
    capabilities.assert_consumed()
    return ScenarioObservation(
        scenario_id=str(spec["id"]),
        runs=tuple(runs),
        prompt_calls=tuple(_prompt_call(request) for request in model.calls),
        tool_calls=tuple(capabilities.calls))


def _normalise(value: Any) -> Any:
    return json.loads(json.dumps(value, sort_keys=True))


# Pinned below after the first measurement; the test is the record.
SCENARIO_DIGESTS: dict[str, str] = {'S1': '4a72a7e33fcb7a5293a74c6c2a06ec1947372d4e3c788ac21cd6fcc677e61192', 'S2': 'cf32bd51ccbff97c21b28107dbb14fa91cf768176957c42dc56f1a348b7162c7', 'S3': 'e778d77321fedf7ebe41e7c0b6f2080966a54d0f5453513bbf547d3db8f869b3', 'S4': '3fcca54627cd865474454f33e1ad13638d3e8d5a928fa14e22a499ac7dda200d', 'S5': '9f763e00792317f30c63af5e28eaa962683dac892d908ad8ce320aa5e38d7074', 'S6': '9649e90d6fe350baa402bb04e40bcbefe4938c203e64a800f5e64f9f5b2aeb63', 'S7': '1c7d38df4b8899f0fe4b27f6c605c6e4b5595cd8f88bc2a9522f789b0eb600aa', 'S8': 'f86478c2951294a3df4f8d3d841314723e44cb1b2a31c86380145002219b67eb'}
CORPUS_DIGEST = '44beb12e56ee87abed53bea14bab2dd48c4000809ba07af0ff3b8900df8f8f29'
BASELINE: dict[str, Any] = json.loads(r'''{
  "admitted": 19,
  "duplicate": 1,
  "intent_refused": 0,
  "other_refusals": 2,
  "runs": 13,
  "scenarios": [
    {
      "admitted": 1,
      "child_admitted": 0,
      "child_intent_refused": 0,
      "child_runs": 0,
      "child_termination_mix": {
        "CANCELLED": 0,
        "OTHER": 0,
        "SUCCEEDED": 0,
        "TIMEOUT": 0,
        "TOOL_FAILED": 0
      },
      "child_trace_digests": [],
      "duplicate": 0,
      "intent_refused": 0,
      "other_refusals": 0,
      "prompt": {
        "calls": 1,
        "max": 148,
        "median": 148,
        "min": 148
      },
      "repeat_tool_rate": 0.0,
      "review_cap": 0,
      "review_rounds": 0,
      "review_verdicts": [],
      "run_id": "run_e272a87953263c87d26fbf01428a1aeb",
      "scenario": "S1",
      "state": "SUCCEEDED",
      "termination": "STOP_WHEN",
      "tick_new_evidence": [
        1
      ],
      "ticks": 1,
      "ticks_to_stability": null,
      "tool_calls": 1,
      "trace_digest": "d0d8913e98dc21df86be6f626275f684139ff46ab704041a43584c33def2117f"
    },
    {
      "admitted": 2,
      "child_admitted": 0,
      "child_intent_refused": 0,
      "child_runs": 0,
      "child_termination_mix": {
        "CANCELLED": 0,
        "OTHER": 0,
        "SUCCEEDED": 0,
        "TIMEOUT": 0,
        "TOOL_FAILED": 0
      },
      "child_trace_digests": [],
      "duplicate": 0,
      "intent_refused": 0,
      "other_refusals": 0,
      "prompt": {
        "calls": 2,
        "max": 485,
        "median": 312.5,
        "min": 140
      },
      "repeat_tool_rate": 0.0,
      "review_cap": 0,
      "review_rounds": 0,
      "review_verdicts": [],
      "run_id": "run_e2713451430799579510ca0c18095609",
      "scenario": "S2",
      "state": "SUCCEEDED",
      "termination": "STOP_WHEN",
      "tick_new_evidence": [
        1,
        0
      ],
      "ticks": 2,
      "ticks_to_stability": 2,
      "tool_calls": 2,
      "trace_digest": "75d1a73d29e4823ef2c45f0016de4caf53e37b71d25dd5f4bb1c0c6c02cae226"
    },
    {
      "admitted": 1,
      "child_admitted": 0,
      "child_intent_refused": 0,
      "child_runs": 0,
      "child_termination_mix": {
        "CANCELLED": 0,
        "OTHER": 0,
        "SUCCEEDED": 0,
        "TIMEOUT": 0,
        "TOOL_FAILED": 0
      },
      "child_trace_digests": [],
      "duplicate": 1,
      "intent_refused": 0,
      "other_refusals": 0,
      "prompt": {
        "calls": 2,
        "max": 469,
        "median": 296.5,
        "min": 124
      },
      "repeat_tool_rate": 0.5,
      "review_cap": 0,
      "review_rounds": 0,
      "review_verdicts": [],
      "run_id": "run_e51e2e7af377bf863a1e86504a44893b",
      "scenario": "S3",
      "state": "SUCCEEDED",
      "termination": "STOP_WHEN",
      "tick_new_evidence": [
        1,
        0
      ],
      "ticks": 2,
      "ticks_to_stability": 2,
      "tool_calls": 2,
      "trace_digest": "46489456219cfdd9a0e56f0b6cc589602530252886baa8579ca96bc2d72b308c"
    },
    {
      "admitted": 4,
      "child_admitted": 1,
      "child_intent_refused": 0,
      "child_runs": 2,
      "child_termination_mix": {
        "CANCELLED": 0,
        "OTHER": 0,
        "SUCCEEDED": 2,
        "TIMEOUT": 0,
        "TOOL_FAILED": 0
      },
      "child_trace_digests": [
        "443a6989039bf11c2d1c4822795349a9f4e766c3f9fc66bbb5f4ec03cf291e65",
        "eea161b7f7bc202011dcb33ad13a1c4a83432ce6f53b06dd3a50472e02f92052"
      ],
      "duplicate": 0,
      "intent_refused": 0,
      "other_refusals": 0,
      "prompt": {
        "calls": 4,
        "max": 1421,
        "median": 415.0,
        "min": 150
      },
      "repeat_tool_rate": 0.0,
      "review_cap": 2,
      "review_rounds": 2,
      "review_verdicts": [
        "FAIL",
        "PASS"
      ],
      "run_id": "run_3e262fa81b07f9fe09e2b7f6195fc09c",
      "scenario": "S4",
      "state": "SUCCEEDED",
      "termination": "STOP_WHEN",
      "tick_new_evidence": [
        0,
        0
      ],
      "ticks": 2,
      "ticks_to_stability": null,
      "tool_calls": 0,
      "trace_digest": "1b764dff6d1aea9476904e7c6a5178d734e15c3097531d7535497f40a48a579d"
    },
    {
      "admitted": 4,
      "child_admitted": 2,
      "child_intent_refused": 0,
      "child_runs": 2,
      "child_termination_mix": {
        "CANCELLED": 0,
        "OTHER": 0,
        "SUCCEEDED": 2,
        "TIMEOUT": 0,
        "TOOL_FAILED": 0
      },
      "child_trace_digests": [
        "443a6989039bf11c2d1c4822795349a9f4e766c3f9fc66bbb5f4ec03cf291e65",
        "9f94fb98751292b59fc8bbc6c82d31ec1c2c4a40d477fc5cdf0ad57dcc819004"
      ],
      "duplicate": 0,
      "intent_refused": 0,
      "other_refusals": 0,
      "prompt": {
        "calls": 4,
        "max": 1421,
        "median": 410.0,
        "min": 140
      },
      "repeat_tool_rate": 0.0,
      "review_cap": 2,
      "review_rounds": 2,
      "review_verdicts": [
        "FAIL",
        "FAIL"
      ],
      "run_id": "run_8988759e1ee73bfadf8c05120c17312e",
      "scenario": "S5",
      "state": "SUCCEEDED",
      "termination": "STOP_WHEN",
      "tick_new_evidence": [
        0,
        0
      ],
      "ticks": 2,
      "ticks_to_stability": null,
      "tool_calls": 0,
      "trace_digest": "3ebbbe731b67e5eb539c075fd133f64f4c94970e28550653e1f892fdcabc4ba6"
    },
    {
      "admitted": 1,
      "child_admitted": 0,
      "child_intent_refused": 0,
      "child_runs": 0,
      "child_termination_mix": {
        "CANCELLED": 0,
        "OTHER": 0,
        "SUCCEEDED": 0,
        "TIMEOUT": 0,
        "TOOL_FAILED": 0
      },
      "child_trace_digests": [],
      "duplicate": 0,
      "intent_refused": 0,
      "other_refusals": 1,
      "prompt": {
        "calls": 1,
        "max": 138,
        "median": 138,
        "min": 138
      },
      "repeat_tool_rate": 0.0,
      "review_cap": 0,
      "review_rounds": 0,
      "review_verdicts": [],
      "run_id": "run_bbd745eb59df03e4bc4865bbf0e5c59e",
      "scenario": "S6",
      "state": "FAILED",
      "termination": "TOOL_FAILED",
      "tick_new_evidence": [
        1
      ],
      "ticks": 1,
      "ticks_to_stability": null,
      "tool_calls": 1,
      "trace_digest": "a2fab43e12af0c49089e7746714de9b0dd78c54a4af1acbd02c62395cf277acb"
    },
    {
      "admitted": 1,
      "child_admitted": 0,
      "child_intent_refused": 0,
      "child_runs": 0,
      "child_termination_mix": {
        "CANCELLED": 0,
        "OTHER": 0,
        "SUCCEEDED": 0,
        "TIMEOUT": 0,
        "TOOL_FAILED": 0
      },
      "child_trace_digests": [],
      "duplicate": 0,
      "intent_refused": 0,
      "other_refusals": 1,
      "prompt": {
        "calls": 1,
        "max": 144,
        "median": 144,
        "min": 144
      },
      "repeat_tool_rate": 0.0,
      "review_cap": 0,
      "review_rounds": 0,
      "review_verdicts": [],
      "run_id": "run_d486840372ab2efd2fd6949888ae4880",
      "scenario": "S7",
      "state": "FAILED",
      "termination": "TIMEOUT",
      "tick_new_evidence": [
        0
      ],
      "ticks": 1,
      "ticks_to_stability": null,
      "tool_calls": 0,
      "trace_digest": "52bf20958f9fa7f3383c694f5c4c2d79fc9923e0651330b6271bf42f05e24652"
    },
    {
      "admitted": 1,
      "child_admitted": 1,
      "child_intent_refused": 0,
      "child_runs": 1,
      "child_termination_mix": {
        "CANCELLED": 0,
        "OTHER": 0,
        "SUCCEEDED": 1,
        "TIMEOUT": 0,
        "TOOL_FAILED": 0
      },
      "child_trace_digests": [
        "bae2c4959cc730137e1dca695bb2cfde83ea1d99793ae2c0d9303d4be2c5c92c"
      ],
      "duplicate": 0,
      "intent_refused": 0,
      "other_refusals": 0,
      "prompt": {
        "calls": 2,
        "max": 128,
        "median": 96.0,
        "min": 64
      },
      "repeat_tool_rate": 0.0,
      "review_cap": 0,
      "review_rounds": 0,
      "review_verdicts": [],
      "run_id": "run_9d7e2f705307e733e625386164b28b56",
      "scenario": "S8",
      "state": "SUCCEEDED",
      "termination": "TICK_LIMIT",
      "tick_new_evidence": [
        0
      ],
      "ticks": 1,
      "ticks_to_stability": null,
      "tool_calls": 0,
      "trace_digest": "f726a801d66069e3bffaff68959e7509d514694b38b6212de6ca943a39d8ae1e"
    }
  ],
  "termination_mix": {
    "CANCELLED": 0,
    "OTHER": 0,
    "SUCCEEDED": 11,
    "TIMEOUT": 1,
    "TOOL_FAILED": 1
  }
}''')


def test_corpus_digests_are_pinned() -> None:
    assert {spec["id"]: scenario_digest(spec) for spec in SCENARIOS} == \
        SCENARIO_DIGESTS
    assert corpus_digest() == CORPUS_DIGEST


def test_loop_baseline_vector_is_pinned() -> None:
    observations = [run_scenario(spec) for spec in SCENARIOS]
    assert _normalise(aggregate_metrics(observations)) == BASELINE


def test_two_consecutive_runs_are_identical() -> None:
    first = [run_scenario(spec) for spec in SCENARIOS]
    second = [run_scenario(spec) for spec in SCENARIOS]
    assert _normalise(aggregate_metrics(first)) == \
        _normalise(aggregate_metrics(second))
    assert [(item.scenario_id,
             tuple(run.trace_digest for run in item.runs)) for item in first] \
        == [(item.scenario_id,
             tuple(run.trace_digest for run in item.runs)) for item in second]


def test_baseline_has_no_composite_score() -> None:
    observations = [run_scenario(spec) for spec in SCENARIOS]
    aggregate = aggregate_metrics(observations)
    assert "quality" not in aggregate
    assert "score" not in aggregate
    # The vector is per-scenario; no scalar summary is exposed.
    assert isinstance(aggregate["scenarios"], list)
    assert all(isinstance(row, dict) for row in aggregate["scenarios"])


if __name__ == "__main__":
    observations = [run_scenario(spec) for spec in SCENARIOS]
    print(json.dumps(_normalise(aggregate_metrics(observations)),
                     indent=2, sort_keys=True))
    print("SCENARIO_DIGESTS =", json.dumps(
        {spec["id"]: scenario_digest(spec) for spec in SCENARIOS},
        indent=2, sort_keys=True))
    print("CORPUS_DIGEST =", corpus_digest())
