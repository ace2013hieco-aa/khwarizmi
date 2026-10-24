"""LOOP observations — the collector's faithfulness proof and its own contract.

The first test is the whole point of the slice: the scripted corpus from
``tests/test_loop_baseline.py``, run through the collector, must reproduce
``docs/LOOP-BASELINE.md``'s pinned vector exactly — row for row, digest for
digest. If it does not, the collector is wrong; the baseline is not re-pinned.

The rest pin what the baseline cannot:

* a live-shaped run over a recorded transport yields a complete vector;
* the capability wrapper counts actual invocations only — a call the runtime
  refuses before the port is not a tool call;
* an unwrapped port reports ``n/a``, never a zero that reads as a measurement;
* two collections of one run are equal.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from hermes.agents.runtime.config import ProfileSpec
from hermes.agents.runtime.run import AgentRuntime
from hermes.agents.runtime.types import ProposalSet, RunLimits, TaskContext, digest_of
from hermes.eval.loop_metrics import aggregate_metrics, scenario_metrics
from hermes.eval.loop_observations import (
    M1,
    M2,
    CollectedScenario,
    RecordingCapabilityPort,
    RecordingModelPort,
    collect_scenario,
    measure_prompt,
)
from hermes.security.boundaries import UntrustedContent
from hermes.tools.models.router import ModelRefusal, ModelRequest
from tests.test_loop_baseline import (
    _TWO_ROUND_REVIEW,
    BASELINE,
    SCENARIOS,
    _as_profile,
    _Clock,
    _context,
    _critic,
    _evidence,
    _normalise,
    _parent,
    _RecordingApplier,
    _ScriptedCapabilities,
    _ScriptedModel,
    _worker,
)


def _task_context(context: Mapping[str, Any]) -> TaskContext:
    """The baseline's task context, rebuilt from the same committed fields."""
    return TaskContext(
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


@dataclass
class _Ran:
    """One executed scenario, with the ports the collector will be handed."""

    spec: Mapping[str, Any]
    runtime: AgentRuntime
    result: ProposalSet
    profiles: Mapping[str, ProfileSpec]
    scripted: _ScriptedModel
    model: RecordingModelPort
    inner_capabilities: _ScriptedCapabilities
    capabilities: RecordingCapabilityPort

    def collect(self, *, with_model: bool = True,
                with_capabilities: bool = True) -> CollectedScenario:
        """Collect this run; ``False`` says that port was not in the path."""
        return collect_scenario(
            scenario_id=str(self.spec["id"]),
            result=self.result,
            surface=self.runtime,
            supervisor=self.runtime.supervisor,
            profiles=self.profiles,
            model=self.model if with_model else None,
            capabilities=self.capabilities if with_capabilities else None)


def _run(spec: Mapping[str, Any]) -> _Ran:
    """Drive one scenario through the *wrapped* ports (the collector's path)."""
    profiles = {name: _as_profile(item)
                for name, item in spec["profiles"].items()}
    clock = _Clock()
    scripted = _ScriptedModel(
        spec["model"], clock=clock,
        advance_first_call=float(spec["advance_first_call"]))
    model = RecordingModelPort(scripted)
    inner_capabilities = _ScriptedCapabilities(spec["tools"])
    capabilities = RecordingCapabilityPort(inner_capabilities)
    runtime = AgentRuntime(
        model=model, orchestration=_RecordingApplier(),
        capabilities=capabilities, profiles=profiles, clock=clock,
        monotonic=clock.monotonic)
    result = runtime.run(str(spec["root_profile"]),
                         _task_context(spec["context"]))
    return _Ran(spec=spec, runtime=runtime, result=result, profiles=profiles,
                scripted=scripted, model=model,
                inner_capabilities=inner_capabilities,
                capabilities=capabilities)


# ═══════════════════════ §4 — faithfulness ═══════════════════════


def test_collector_reproduces_the_pinned_baseline_row_for_row() -> None:
    runs = [_run(spec) for spec in SCENARIOS]
    collected = [ran.collect() for ran in runs]
    for ran in runs:
        ran.scripted.assert_consumed()
        ran.inner_capabilities.assert_consumed()

    # Every corpus scenario is fully measurable: the collector was in both
    # ports' call paths, so nothing may be reported as unmeasured.
    assert [item.unmeasured for item in collected] == [()] * len(SCENARIOS)

    actual = _normalise(aggregate_metrics([item.observation
                                           for item in collected]))
    pinned = {row["scenario"]: row for row in BASELINE["scenarios"]}
    assert set(pinned) == {row["scenario"] for row in actual["scenarios"]}
    for row in actual["scenarios"]:
        assert row == pinned[row["scenario"]], f"{row['scenario']} moved"
    assert actual == BASELINE

    # The wrapper records the same identities the scripted port recorded for
    # itself — same calls, same order, same argument digests.
    for ran, item in zip(runs, collected, strict=True):
        assert item.observation.tool_calls == tuple(ran.inner_capabilities.calls)
        assert len(item.observation.prompt_calls) == len(ran.scripted.calls)


# ═══════════════════════ live-shaped run ═══════════════════════

_LIVE: Mapping[str, Any] = {
    "id": "LIVE-1",
    "root_profile": "researcher",
    "profiles": {
        "researcher": _parent(
            tools=("source_search",),
            structured=("proposals", "tool_calls", "delegations"),
            stop_when="converged", max_ticks=3,
            review=_TWO_ROUND_REVIEW),
        "critic": _critic(),
        "worker": _worker(),
    },
    "model": {
        "researcher": [
            {"kind": "INSERT_TASK", "rationale": "live draft 1",
             "payload": {"spec": {"stage": "LIVE", "step": 1}},
             "tool_calls": [{"capability_id": "source_search",
                             "arguments": {"query": "alpha"},
                             "rationale": "gather alpha"}],
             "delegations": [{"profile": "worker",
                              "spec": {"stage": "LIVE-child"},
                              "task_type": "AGENT_TASK"}]},
            {"kind": "INSERT_TASK", "rationale": "live draft 2",
             "payload": {"spec": {"stage": "LIVE", "step": 2}},
             "tool_calls": [{"capability_id": "source_search",
                             "arguments": {"query": "beta"},
                             "rationale": "gather beta"}]},
            {"kind": "INSERT_TASK", "rationale": "live draft 3",
             "payload": {"spec": {"stage": "LIVE", "step": 3}}},
        ],
        "critic": [{}],
        "worker": [{"kind": "INSERT_TASK", "rationale": "live child draft",
                    "payload": {"spec": {"stage": "LIVE-child"}}}],
    },
    "tools": [
        _evidence("LIVE evidence alpha", "artifact:LIVE:alpha"),
        _evidence("LIVE evidence beta", "artifact:LIVE:beta"),
    ],
    "context": _context(
        "LIVE", stage="live-shaped", methodology="three ticks, two tools, "
        "one child and one review", predecessor="none"),
    "advance_first_call": 0.0,
}


def test_live_shaped_run_produces_a_complete_vector() -> None:
    ran = _run(_LIVE)
    collected = ran.collect()
    ran.scripted.assert_consumed()
    ran.inner_capabilities.assert_consumed()
    vector = collected.vector()

    assert collected.unmeasured == ()
    # M1 — three parent calls, one reviewer, one child.
    assert vector["prompt"]["calls"] == 5
    assert vector["prompt"]["min"] > 0
    # M2 — two distinct invocations, no repeat.
    assert vector["tool_calls"] == 2
    assert vector["repeat_tool_rate"] == 0.0
    # M3 — one new identity per tool tick, then the silent tick.
    assert vector["tick_new_evidence"] == (1, 1, 0)
    assert vector["ticks_to_stability"] == 3
    # M4 — one consumed verdict against a declared cap of two.
    assert (vector["review_rounds"], vector["review_cap"]) == (1, 2)
    assert vector["review_verdicts"] == ("PASS",)
    # M5/M6 — the closed termination set, and the root's admissions.
    assert (vector["state"], vector["termination"]) == ("SUCCEEDED", "STOP_WHEN")
    assert vector["admitted"] == 5
    assert (vector["duplicate"], vector["intent_refused"]) == (0, 0)
    assert vector["other_refusals"] == 0
    # Child accounting: the delegated worker and the review child.
    assert vector["child_runs"] == 2
    assert vector["child_admitted"] == 1
    assert vector["child_termination_mix"]["OTHER"] == 0
    # M0 — the trace digest is a recorded SHA-256, not a placeholder.
    assert len(vector["trace_digest"]) == 64
    assert all(ch in "0123456789abcdef" for ch in vector["trace_digest"])
    # Nothing in this run was genuinely unavailable.
    assert "n/a" not in str(_normalise(vector))


# ═══════════════════════ actual invocations only ═══════════════════════

_REFUSED: Mapping[str, Any] = {
    "id": "REFUSED-1",
    "root_profile": "researcher",
    "profiles": {"researcher": _parent(tools=("source_search",))},
    "model": {"researcher": [{
        "kind": "INSERT_TASK", "rationale": "one real call, three refusals",
        "payload": {"spec": {"stage": "REFUSED"}},
        "tool_calls": [
            {"capability_id": "outside_scope", "arguments": {"query": "x"},
             "rationale": "a capability the profile does not open"},
            {"arguments": {"query": "y"},
             "rationale": "no capability id at all"},
            {"capability_id": "source_search",
             "arguments": ["not", "a", "mapping"],
             "rationale": "arguments that are not a mapping"},
            {"capability_id": "source_search", "arguments": {"query": "ok"},
             "rationale": "the one call that actually happens"},
        ],
    }]},
    "tools": [_evidence("REFUSED evidence", "artifact:REFUSED:evidence")],
    "context": _context(
        "REFUSED", stage="refusals", methodology="one invoked call of four",
        predecessor="none"),
    "advance_first_call": 0.0,
}


def test_capability_wrapper_counts_only_actual_invocations() -> None:
    ran = _run(_REFUSED)
    collected = ran.collect()
    ran.inner_capabilities.assert_consumed()

    # Three of the four declared calls are refused before the port: outside the
    # profile's tools, no capability id, and arguments that are not a mapping.
    assert len(ran.capabilities.calls) == 1
    assert ran.capabilities.calls[0].capability_id == "source_search"
    assert ran.capabilities.calls[0].arguments_digest == digest_of({"query": "ok"})
    # The runtime's own counter agrees with the wrapper.
    assert ran.result.tool_calls == 1

    vector = collected.vector()
    assert vector["tool_calls"] == 1
    assert vector["repeat_tool_rate"] == 0.0
    assert vector["other_refusals"] == 3


# ═══════════════════════ n/a, never a silent zero ═══════════════════════


def test_unwrapped_capability_port_reports_na_never_zero() -> None:
    ran = _run(_LIVE)
    collected = ran.collect(with_capabilities=False)

    assert collected.unmeasured == (M2,)
    vector = collected.vector()
    assert vector["repeat_tool_rate"] == "n/a"
    assert vector["tool_calls"] == "n/a"
    # Only the unobserved metric is n/a: M1 and M3-M6 were still read.
    assert vector["prompt"]["calls"] == 5
    assert vector["ticks_to_stability"] == 3
    assert vector["admitted"] == 5
    # The binding function is untouched — this is the collector's report, not a
    # change to loop_metrics' definition.
    assert scenario_metrics(collected.observation)["repeat_tool_rate"] == 0.0


def test_unwrapped_model_port_reports_na_for_m1() -> None:
    ran = _run(_LIVE)
    collected = ran.collect(with_model=False)

    assert collected.unmeasured == (M1,)
    vector = collected.vector()
    assert vector["prompt"] == "n/a"
    assert vector["tool_calls"] == 2
    assert vector["ticks_to_stability"] == 3


# ═══════════════════════ determinism ═══════════════════════


def test_two_collections_of_the_same_run_are_equal() -> None:
    ran = _run(_LIVE)
    first = ran.collect()
    second = ran.collect()

    assert first == second
    assert first.observation.runs == second.observation.runs
    assert first.vector() == second.vector()


def test_two_runs_of_one_scenario_agree() -> None:
    first = _run(_LIVE).collect().vector()
    second = _run(_LIVE).collect().vector()

    assert _normalise(first) == _normalise(second)
    assert first["trace_digest"] == second["trace_digest"]


# ═══════════════════════ the M1 rule itself ═══════════════════════


def test_prompt_measurement_counts_payload_but_not_the_tick_marker() -> None:
    prompt = (
        UntrustedContent(text="body", origin="runtime.payload", ref="r1"),
        UntrustedContent(text="tick 1 of 2", origin="runtime.tick", ref="task"),
    )
    call = measure_prompt(prompt)

    assert call.payload_bytes == len("body")
    assert call.marker_bytes == (
        len("tick 1 of 2") + len("runtime.payload") + len("r1")
        + len("runtime.tick") + len("task"))
    assert call.total_bytes == call.payload_bytes + call.marker_bytes


class _RefusingModel:
    """A model port that refuses every request (no proposal, no provider)."""

    def invoke(self, request: ModelRequest) -> ModelRefusal:
        return ModelRefusal(code="MALFORMED_PAYLOAD", detail="refused",
                            tier=request.tier)


def test_a_refused_request_is_still_a_model_call() -> None:
    recorder = RecordingModelPort(_RefusingModel())
    request = ModelRequest(
        tier="research", profile="researcher", lease_generation="gen-1",
        prompt=(UntrustedContent(text="hello", origin="runtime.payload",
                                 ref="r1"),))

    result = recorder.invoke(request)

    assert isinstance(result, ModelRefusal)
    assert len(recorder.calls) == 1
    assert recorder.calls[0].payload_bytes == len("hello")
