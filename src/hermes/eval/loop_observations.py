"""LOOP observations — collect a real run's surfaces into the LOOP-M shapes.

``hermes.eval.loop_metrics`` is a pure function over observations: no I/O, no
clock, no DB, no model call. This module is its missing other half — the
collector that turns a run's *observable* surfaces into those observations, so a
live run produces a vector instead of a trace nobody can interpret.

Nothing here instruments the runtime
------------------------------------
No event kind, ``detail`` field, checkpoint field or write is added, and no
module under ``hermes.agents.runtime`` is imported for its side effects. The
runtime is read through what it already exposes — ``ProposalSet``, the terminal
``Checkpoint``, ``Supervisor.trace_digest`` — and the two facts it cannot report
are collected by wrapping the ports the caller already injects:

* :class:`RecordingModelPort` wraps a ``ModelPort`` and measures each
  ``ModelRequest``'s prompt envelopes at call time (:func:`measure_prompt`),
  retaining the byte counts and no text;
* :class:`RecordingCapabilityPort` wraps a ``CapabilityPort`` and records
  ``(capability_id, sha256(canonical arguments))`` for each **actual**
  invocation, before delegating.

The model plane's own record/replay (``hermes.tools.providers.replay``) records
a provider-level ``RequestSpec`` — url, params, body — not the built
``ModelRequest`` with its origin-marked envelopes. The envelope origins *are*
the M1 measurement (payload text versus the tick marker and the origin/ref
labels), so that plane cannot supply M1; a thin port wrapper is the reuse path,
not a second instrument.

The faithfulness rule
---------------------
Pointed at the scripted corpus, this collector must reproduce
``docs/LOOP-BASELINE.md``'s pinned vector exactly. If it disagrees, the
collector is wrong — the baseline is not re-pinned.
``tests/test_loop_observations.py`` is that proof.

M2 is ``n/a`` or a measurement, never a silent zero
---------------------------------------------------
``ScenarioObservation.tool_calls`` cannot express "not measured": an empty tuple
and an unobserved run are the same value, and ``repeat_tool_rate(())`` is
``0.0`` — a claim ("no repeats") nobody made. :class:`CollectedScenario`
therefore carries the ``ScenarioObservation`` *plus* the metric ids the collector
could not observe, and :meth:`CollectedScenario.vector` renders those as
``"n/a"``. ``loop_metrics`` is untouched: its definitions are binding, and a
caller who bypasses ``vector()`` gets exactly the old reading.

What it does not do
-------------------
No I/O beyond the objects it is handed, no clock, no DB, no model call, no
capability call of its own. It originates nothing: every invocation it records
was made by the runtime through the port it wrapped. It writes no checkpoint and
no event, and holds no store.

Import discipline: ``hermes.agents.runtime.*`` (shapes and the supervisor),
``hermes.eval.loop_metrics``, ``hermes.tools.*`` port types, ``hermes.security``
(the envelope), and stdlib. Never ``hermes.persistence``, never
``hermes.research``.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any, Protocol

from hermes.agents.runtime.config import ProfileSpec
from hermes.agents.runtime.run import CapabilityPort, ModelPort
from hermes.agents.runtime.supervisor import Supervisor
from hermes.agents.runtime.types import (
    Admission,
    Checkpoint,
    ProposalSet,
    ToolFeedback,
    digest_of,
)
from hermes.eval.loop_metrics import (
    PromptCall,
    RunObservation,
    ScenarioObservation,
    ToolCall,
    scenario_metrics,
)
from hermes.security.boundaries import UntrustedContent
from hermes.tools.capabilities.types import (
    CapabilityRefusal,
    InvokeRequest,
    Observation,
)
from hermes.tools.models.router import (
    ModelProposal,
    ModelRefusal,
    ModelRequest,
)

__all__ = [
    "M1",
    "M2",
    "CheckpointSurface",
    "CollectedScenario",
    "ObservationError",
    "RecordingCapabilityPort",
    "RecordingModelPort",
    "collect_run",
    "collect_scenario",
    "measure_prompt",
]

#: The origin the runtime marks a tick's own marker envelope with. The metric
#: definition excludes it (and every origin/ref label) from M1's payload bytes;
#: the runtime writes it as a literal in ``run.py``, so it is restated here
#: rather than imported from a private constant that does not exist.
_TICK_ORIGIN = "runtime.tick"

#: Metric ids a collection can report as unmeasured. ``"n/a"`` is the only
#: honest value for a metric whose collector was not in the call path.
M1 = "M1"
M2 = "M2"

#: The rows ``vector()`` replaces when a metric was not observed. Replacing the
#: count as well as the rate is deliberate: ``tool_calls == 0`` beside
#: ``repeat_tool_rate == "n/a"`` would still read as "no calls happened".
_NA_ROWS: Mapping[str, Mapping[str, object]] = {
    M1: {"prompt": "n/a"},
    M2: {"tool_calls": "n/a", "repeat_tool_rate": "n/a"},
}


class ObservationError(ValueError):
    """A run surface the collector cannot read — refused, never guessed.

    Raised at collection time, before a vector exists: a missing root report, a
    missing terminal checkpoint, or a profile the handed map does not declare.
    A collector that filled these in would be inventing the run it claims to
    have measured.
    """


class CheckpointSurface(Protocol):
    """The read-only checkpoint accessor the collector needs from a run surface.

    ``AgentRuntime`` and ``RuntimeWiring`` both expose exactly this method, so
    the collector never holds a store: it asks the surface for one checkpoint at
    a time and treats ``None`` as an error rather than an empty run.
    """

    def checkpoint(self, run_id: str) -> Checkpoint | None: ...


def measure_prompt(prompt: Iterable[UntrustedContent]) -> PromptCall:
    """M1 for one request: payload bytes, marker bytes, and their sum.

    Every envelope's ``text`` counts as payload unless its origin is the tick
    marker. The origin and ref labels count as markers, never as payload: they
    are the router's bookkeeping, not content the model was asked to read.
    """
    payload = 0
    marker = 0
    for part in prompt:
        text_bytes = len(part.text.encode("utf-8"))
        if part.origin == _TICK_ORIGIN:
            marker += text_bytes
        else:
            payload += text_bytes
        marker += len(part.origin.encode("utf-8"))
        marker += len(str(part.ref).encode("utf-8"))
    return PromptCall(payload_bytes=payload, marker_bytes=marker,
                      total_bytes=payload + marker)


class RecordingModelPort:
    """A ``ModelPort`` that measures each request, then delegates.

    The measurement is taken at call time and only the counts are retained, so
    the collector never becomes a second copy of the prompt. The record is
    appended *before* the inner port answers: a request that ends in a
    ``ModelRefusal`` was still a model call with a payload, and M1 measures the
    question, not the answer.
    """

    def __init__(self, inner: ModelPort) -> None:
        self._inner = inner
        self._calls: list[PromptCall] = []

    def invoke(self, request: ModelRequest) -> ModelProposal | ModelRefusal:
        self._calls.append(measure_prompt(request.prompt))
        return self._inner.invoke(request)

    @property
    def calls(self) -> tuple[PromptCall, ...]:
        """One ``PromptCall`` per request the runtime issued, in order."""
        return tuple(self._calls)


class RecordingCapabilityPort:
    """A ``CapabilityPort`` that records each actual invocation, then delegates.

    The runtime refuses a malformed call, a capability outside the profile's
    declared tools, and a call with no port wired *before* it ever reaches this
    object, so those are not tool calls here — the port never saw them. The
    record is appended before delegation for the same reason as the model port:
    an invocation that the inner port answers with a refusal or a failure did
    happen, and M2's denominator is what happened.
    """

    def __init__(self, inner: CapabilityPort) -> None:
        self._inner = inner
        self._calls: list[ToolCall] = []

    def invoke(self, request: InvokeRequest) -> Observation | CapabilityRefusal:
        self._calls.append(ToolCall(
            capability_id=request.capability_id,
            arguments_digest=digest_of(dict(request.arguments))))
        return self._inner.invoke(request)

    @property
    def calls(self) -> tuple[ToolCall, ...]:
        """One ``ToolCall`` per invocation the runtime actually made, in order."""
        return tuple(self._calls)


@dataclass(frozen=True, slots=True)
class CollectedScenario:
    """A scenario's observation plus the metrics its collection could not see.

    ``unmeasured`` holds metric ids (``M1``, ``M2``) — never a value. Keeping
    the fact beside the observation is what makes ``"n/a"`` expressible without
    changing ``ScenarioObservation``, whose empty ``tool_calls`` would otherwise
    be indistinguishable from a measured zero.
    """

    observation: ScenarioObservation
    unmeasured: tuple[str, ...] = ()

    def vector(self) -> dict[str, Any]:
        """The M0-M6 vector, with each unmeasured metric rendered ``"n/a"``.

        Identical to ``scenario_metrics(observation)`` when nothing is
        unmeasured. An unknown metric id raises ``KeyError`` rather than
        passing through: a typo must not silently leave a zero in place.
        """
        vector = scenario_metrics(self.observation)
        for metric in self.unmeasured:
            vector.update(_NA_ROWS[metric])
        return vector


def collect_run(
    *,
    checkpoint: Checkpoint,
    supervisor: Supervisor,
    profiles: Mapping[str, ProfileSpec],
    is_root: bool,
    result: ProposalSet | None = None,
) -> RunObservation:
    """One run's M0-M6 facts, read from its report and terminal checkpoint.

    The root reads its state from the ``ProposalSet`` the runtime returned (the
    plane's own account of the run) and its feedback from the terminal
    checkpoint; a child has no ``ProposalSet``, so its terminal checkpoint is the
    whole surface. M0 is recorded verbatim from the supervisor's trace digest —
    never recomputed here, so the digest stays the trace's claim and not the
    collector's.
    """
    if is_root:
        if result is None:
            raise ObservationError(
                "a root run is collected from its ProposalSet; none was given")
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
    profile = profiles.get(profile_name)
    if profile is None:
        raise ObservationError(
            f"run {run_id!r} reports profile {profile_name!r}, which the "
            f"handed profile map does not declare ({sorted(profiles)})")
    intent_refused = sum(1 for proposal in proposals
                         if proposal.admission == Admission.REFUSED.value)
    return RunObservation(
        run_id=run_id,
        profile=profile_name,
        is_root=is_root,
        state=state,
        termination=termination,
        ticks=ticks,
        trace_digest=supervisor.trace_digest(run_id),
        admitted=sum(1 for proposal in proposals
                     if proposal.admission == Admission.ADMITTED.value),
        duplicate=sum(1 for proposal in proposals
                      if proposal.admission == Admission.DUPLICATE.value),
        intent_refused=intent_refused,
        other_refusals=max(0, len(refusals) - intent_refused),
        review_rounds=len(verdicts),
        review_cap=(profile.review.max_review_rounds
                    if profile.review.required else 0),
        review_verdicts=tuple("PASS" if verdict.passed else "FAIL"
                              for verdict in verdicts),
        tick_new_evidence=_tick_new_evidence(checkpoint.feedback, ticks),
    )


def collect_scenario(
    *,
    scenario_id: str,
    result: ProposalSet,
    surface: CheckpointSurface,
    supervisor: Supervisor,
    profiles: Mapping[str, ProfileSpec],
    model: RecordingModelPort | None = None,
    capabilities: RecordingCapabilityPort | None = None,
) -> CollectedScenario:
    """One scenario's observation, from its root report and every run's checkpoint.

    ``model`` and ``capabilities`` are the recorders that were actually in the
    call path. Passing ``None`` is the honest statement that this run's path
    could not be wrapped — a handler that constructs its own port, or a caller
    that forgot the wrapper — and it marks M1/M2 unmeasured instead of reporting
    a zero nobody observed.

    The caller's statement is the only source of that fact: a recorder shared
    across two runs, or one that wrapped only some of a run's invocations, still
    looks measured from here, and the collector cannot tell from the outside.
    One recorder per runtime is therefore the contract, not a convention.

    Child runs are resolved from the root's delegation records, in order and
    de-duplicated, exactly as the baseline corpus does: a review child and a
    delegated worker are both children of the run that produced them.
    """
    root_checkpoint = surface.checkpoint(result.run_id)
    if root_checkpoint is None:
        raise ObservationError(
            f"no terminal checkpoint for root run {result.run_id!r}")
    runs = [collect_run(checkpoint=root_checkpoint, supervisor=supervisor,
                        profiles=profiles, is_root=True, result=result)]
    child_ids: list[str] = []
    for record in result.delegations:
        child_run_id = record.child_run_id
        if not child_run_id or child_run_id in child_ids:
            continue
        child_ids.append(child_run_id)
        child_checkpoint = surface.checkpoint(child_run_id)
        if child_checkpoint is None:
            raise ObservationError(
                f"no terminal checkpoint for child run {child_run_id!r} of "
                f"{result.run_id!r}")
        runs.append(collect_run(checkpoint=child_checkpoint,
                                supervisor=supervisor, profiles=profiles,
                                is_root=False))
    unmeasured: list[str] = []
    prompt_calls: tuple[PromptCall, ...] = ()
    tool_calls: tuple[ToolCall, ...] = ()
    if model is None:
        unmeasured.append(M1)
    else:
        prompt_calls = model.calls
    if capabilities is None:
        unmeasured.append(M2)
    else:
        tool_calls = capabilities.calls
    return CollectedScenario(
        observation=ScenarioObservation(
            scenario_id=scenario_id,
            runs=tuple(runs),
            prompt_calls=prompt_calls,
            tool_calls=tool_calls),
        unmeasured=tuple(unmeasured))


def _tick_new_evidence(feedback: Iterable[ToolFeedback],
                       ticks: int) -> tuple[int, ...]:
    """Per tick, the evidence identities not seen in an earlier tick of the run.

    A tick that produced no feedback contributes ``0`` — it introduced nothing,
    which is exactly what M3's stability point is a statement about.
    """
    seen: set[str] = set()
    fresh: list[int] = []
    records = tuple(feedback)
    for tick in range(1, ticks + 1):
        tick_digests = {record.evidence_digest() for record in records
                        if record.tick == tick}
        fresh.append(len(tick_digests - seen))
        seen.update(tick_digests)
    return tuple(fresh)
