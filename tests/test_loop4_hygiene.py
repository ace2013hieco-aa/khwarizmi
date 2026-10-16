"""LOOP-4 — the LOOP-0 hygiene remainder, closed in one bounded batch.

Each pin below corresponds to one triaged item and states the *verdict* it
carries. The items were adjudicated by `AUDIT-LOOP-0-TRIAGE.md` as VALID on the
tree this branch was cut from; a VALID item is fixed here and pinned, and the two
items the triage classified STALE / NOT-A-BUG are pinned as *confirmed non-bugs*
rather than changed.

| Item | Verdict | Pin |
| --- | --- | --- |
| E2 | FIXED | `test_a_deadline_that_expires_during_the_terminal_act_times_the_run_out` |
| E3 | FIXED | `test_the_opening_checkpoint_does_not_extend_the_runs_deadline_anchor`, `test_a_resume_continues_the_runs_deadline_and_never_re_grants_it` |
| E5 | FIXED | `test_a_retry_is_asked_with_the_refusal_that_ended_the_previous_attempt`, `test_the_retry_sleep_never_crosses_the_runs_deadline` |
| E6 | FIXED | `test_the_termination_vocabulary_holds_no_dead_member` |
| E7 | FIXED | `test_a_malformed_tool_call_is_refused_and_the_tick_carries_on`, `test_a_capability_the_plane_invoked_and_that_failed_still_stops_the_run` |
| E8 | FIXED | `test_a_draft_carries_the_evidence_it_was_drafted_on` |
| G8 (mid-batch) | FIXED | `test_the_deadline_is_observed_mid_batch_not_only_at_the_tick` |
| G8 (`or`-zero) | RECORDED (STALE) | `test_a_zero_limit_defers_to_the_profile_rather_than_disabling` |
| G8 (converged/digest) | RECORDED (NOT-A-BUG) | `test_converged_novelty_is_read_before_the_seen_set_absorbs_it` |

Authority is untouched and that is asserted, not assumed: every fix here is a
bound, a severity or a provenance field on the *drafting* side of the plane. No
pin below approves, records, resolves or mutates anything durable, and none of
them reads model output as an instruction.

Prohibited claims: this pins a deadline, a retry envelope, a severity rule, a
vocabulary and a provenance field. It makes no claim about the validity of any
content a model, a reviewer or a capability carries.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

import pytest

import hermes.agents.runtime.run as run_module
from hermes.agents.runtime.assembly import RETRY_ORIGIN
from hermes.agents.runtime.checkpoint import InMemoryCheckpointStore
from hermes.agents.runtime.config import ProfileSpec, parse_profile
from hermes.agents.runtime.run import AgentRuntime
from hermes.agents.runtime.supervisor import RetryBudget, Supervisor
from hermes.agents.runtime.types import (
    RATIONALE,
    RunLimits,
    TaskContext,
    Termination,
    tool_idempotency_key_of,
)
from hermes.core.intents import Intent
from hermes.tools.capabilities.types import (
    CapabilityRefusal,
    FailureKind,
    Observation,
)
from hermes.tools.models.router import (
    ModelProposal,
    ModelRefusal,
    ModelRequest,
)

STAMP = "2026-10-16T00:00:00+00:00"


# ═══════════════════════ rig ═══════════════════════


def _profile(name: str, *, stop_when: str = "proposals_raised",
             max_ticks: int = 2, kinds: tuple[str, ...] = ("INSERT_TASK",),
             capabilities: tuple[str, ...] = (),
             fields: tuple[str, ...] = ("proposals",),
             review: Mapping[str, Any] | None = None,
             max_model_calls_per_tick: int = 1) -> ProfileSpec:
    document: dict[str, Any] = {
        "version": "1",
        "name": name,
        "role": f"{name} role",
        "agent_profile": "RESEARCHER",
        "model_policy": {"tier": "research",
                         "structured_fields": list(fields)},
        "tools": list(capabilities),
        "authority": {"proposable_kinds": list(kinds),
                      "allowed_capabilities": list(capabilities)},
        "termination": {"max_ticks": max_ticks, "max_proposals": 8,
                        "stop_when": stop_when,
                        "max_model_calls_per_tick": max_model_calls_per_tick},
        "review": dict(review or {"required": False}),
    }
    return parse_profile(document, source=name)


def _reviewed(*, rounds: int | None = None,
              reviewer: str = "critic") -> dict[str, Any]:
    document: dict[str, Any] = {"reviewer_profile": reviewer, "required": True}
    if rounds is not None:
        document["max_review_rounds"] = rounds
    return document


def _context(*, max_ticks: int = 0, deadline_seconds: float | None = None,
             task_id: str = "task-root") -> TaskContext:
    return TaskContext(task_id=task_id, project_id="p1", lease_generation="gen-1",
                       payload={},
                       limits=RunLimits(max_ticks=max_ticks,
                                        deadline_seconds=deadline_seconds))


@dataclass(frozen=True, slots=True)
class _Applied:
    entity_id: str
    duplicate: bool


class _Applier:
    """The Orchestration API fake — records every intent it is handed."""

    def __init__(self) -> None:
        self.calls: list[Intent] = []

    def __call__(self, intent: Intent) -> _Applied:
        self.calls.append(intent)
        return _Applied(entity_id=f"ent_{len(self.calls):04d}", duplicate=False)


class _Clock:
    """A monotonic clock that only moves when a test says so."""

    def __init__(self) -> None:
        self._monotonic = 0.0

    def __call__(self) -> str:
        return STAMP

    def monotonic(self) -> float:
        return self._monotonic

    def advance(self, seconds: float) -> None:
        self._monotonic += seconds


class _Model:
    """A `ModelPort` serving a per-profile script in call order.

    A script entry may be a mapping (a structured proposal), a `ModelRefusal`
    (returned as-is, so a retryable refusal can be scripted) or an exception
    (raised, which is how a crash mid-run is scripted). `on_call` sees the
    request before the entry is served, so a test can move a clock at exactly
    the call it cares about.
    """

    def __init__(self, scripts: Mapping[str, list[Any]], *,
                 on_call: Any = None) -> None:
        self._scripts = {name: list(items) for name, items in scripts.items()}
        self.calls: list[ModelRequest] = []
        self._on_call = on_call

    def invoke(self, request: ModelRequest) -> Any:
        self.calls.append(request)
        if self._on_call is not None:
            self._on_call(request)
        script = self._scripts.get(request.profile)
        if not script:
            return ModelRefusal(code="MALFORMED_PAYLOAD",
                                detail=f"no scripted response for "
                                       f"{request.profile!r}")
        entry = script.pop(0)
        if isinstance(entry, Exception):
            raise entry
        if isinstance(entry, ModelRefusal):
            return entry
        return ModelProposal(provider_id="scripted", model_id="scripted",
                             tier="research", profile=request.profile,
                             lease_generation=request.lease_generation,
                             structured=dict(entry))

    def calls_for(self, profile: str) -> int:
        return sum(1 for request in self.calls if request.profile == profile)

    def prompt_for(self, profile: str, index: int) -> tuple[Any, ...]:
        """The `index`-th prompt the given profile saw (0-based, per profile)."""
        seen = 0
        for request in self.calls:
            if request.profile != profile:
                continue
            if seen == index:
                return request.prompt
            seen += 1
        raise AssertionError(f"{profile!r} made fewer than {index + 1} calls")


class _Capabilities:
    """A `CapabilityPort` fake: a scripted result per call, in order.

    `on_call` sees the request before the result is served, so a test can burn a
    run's remaining bound on exactly the call it cares about.
    """

    def __init__(self, results: list[Any] | None = None, *,
                 on_call: Any = None) -> None:
        self._results = list(results or [])
        self._on_call = on_call
        self.requests: list[Any] = []

    def invoke(self, request: Any) -> Any:
        self.requests.append(request)
        if self._on_call is not None:
            self._on_call(request)
        if not self._results:
            return Observation(capability_id=request.capability_id, status="OK",
                               payload=None, artifacts=())
        return self._results.pop(0)


def _runtime(model: Any, *, profiles: Mapping[str, ProfileSpec],
             applier: _Applier | None = None, capabilities: Any = None,
             checkpoints: Any = None, clock: _Clock | None = None
             ) -> AgentRuntime:
    return AgentRuntime(
        model=model,
        orchestration=applier if applier is not None else _Applier(),
        profiles=dict(profiles), capabilities=capabilities,
        checkpoints=(checkpoints if checkpoints is not None
                     else InMemoryCheckpointStore()),
        clock=clock if clock is not None else (lambda: STAMP),
        monotonic=(clock.monotonic if clock is not None else None))


def _draft(*, rationale: str = "because", kind: str = "INSERT_TASK",
           payload: Mapping[str, Any] | None = None,
           tool_calls: list[Any] | None = None) -> dict[str, Any]:
    document: dict[str, Any] = {
        "proposals": [{"kind": kind, "rationale": rationale,
                       "payload": dict(payload or {"goal": "g"})}]}
    if tool_calls is not None:
        document["tool_calls"] = tool_calls
    return document


def _retry_envelopes(prompt: tuple[Any, ...]) -> list[Any]:
    return [item for item in prompt if item.origin == RETRY_ORIGIN]


# ═══════════════════════ E2 — the terminal act is deadline-checked ═══════════


def test_a_deadline_that_expires_during_the_terminal_act_times_the_run_out(
        ) -> None:
    """E2: the review is the longest part of the run and used to drop the bound.

    `_close` passed `None` where the deadline belongs, so a run whose bound
    expired inside its own review still reported `SUCCEEDED`. The check now
    brackets the terminal act with the run's deadline as well as the cancel.
    """
    clock = _Clock()
    lead = _profile("lead", max_ticks=1, review=_reviewed())
    critic = _profile("critic", max_ticks=1, kinds=("ABANDON",))
    # The reviewer's own call is what burns the run's remaining time.
    model = _Model({"lead": [_draft()], "critic": [_draft(kind="ABANDON")]},
                   on_call=lambda request: (clock.advance(10_000)
                                            if request.profile == "critic"
                                            else None))
    runtime = _runtime(model, profiles={"lead": lead, "critic": critic},
                       clock=clock)
    result = runtime.run("lead", _context(deadline_seconds=5.0))

    assert result.termination == Termination.TIMEOUT.value
    assert result.state == "FAILED"
    assert any("during the terminal act" in refusal.detail
               for refusal in result.refusals)


# ═══════════════════════ E3 — resume continues the run's bound ═══════════════


def test_the_opening_checkpoint_does_not_extend_the_runs_deadline_anchor() -> None:
    """E3/M1: the checkpoint carries an *absolute* anchor, not a remaining budget.

    The opening checkpoint is written on every entry to `_run_spec`, a resume
    included. When it carried a *remaining* duration, that entry re-based the
    duration against its own start, so a run that crashed before completing a
    tick was handed the full declared bound on every resume — the bound never
    shrank and the run was unbounded (driven: 100.0 across five resumes against
    a declared 100.0 s bound). The anchor is an absolute instant, set once and
    re-recorded unchanged, so the opening checkpoint cannot extend it.
    """
    clock = _Clock()
    lead = _profile("lead", max_ticks=3)
    store = InMemoryCheckpointStore()
    context = _context(deadline_seconds=100.0)
    run_id = context.resolved_run_id("lead")

    crashing = _Model({"lead": [RuntimeError("crash before the first tick")]},
                      on_call=lambda _request: clock.advance(10.0))
    runtime = _runtime(crashing, profiles={"lead": lead}, checkpoints=store,
                       clock=clock)
    with pytest.raises(RuntimeError):
        runtime.run("lead", context)

    first = store.get(run_id)
    assert first is not None and first.is_terminal() is False
    # The run's anchor: declared 100 seconds from a run that began at 0.
    assert first.deadline_mono == pytest.approx(100.0)

    # Time passes between the crash and the recovery: the resume begins at 25.
    clock.advance(15.0)
    again = _runtime(_Model({"lead": [RuntimeError("crash again")]},
                            on_call=lambda _request: clock.advance(10.0)),
                     profiles={"lead": lead}, checkpoints=store, clock=clock)
    with pytest.raises(RuntimeError):
        again.resume(run_id, lease_generation="gen-1")

    resumed_opening = store.get(run_id)
    assert resumed_opening is not None
    # The resume's *opening* checkpoint carries the same instant. Had it re-based
    # the bound against its own start it would read 25 + 100 = 125.0.
    assert resumed_opening.deadline_mono == pytest.approx(100.0)
    # And the budget left, measured from that original anchor, has shrunk.
    left = again.supervisor.remaining(resumed_opening.deadline_mono)
    assert left is not None and left == pytest.approx(65.0)
    assert left < 100.0


def test_a_resume_continues_the_runs_deadline_and_never_re_grants_it() -> None:
    """E3/M1: a resume spends the carried instant, not a fresh full bound.

    The run crashes on tick 2 with its anchor still 90 seconds ahead. The resume
    begins at mono 20 with 80 seconds left and its own call then costs 95 — past
    the *carried* anchor of 100 — so its next tick observes the expiry: the run
    reports `TIMEOUT` after exactly **one** model call and stops at mono 115. A
    freshly minted bound (20 + 100 = 120) would have let a *second* call run (to
    mono 210) before the expiry. The resumed run's model-call count and its
    terminal instant are therefore what pin the carry — both change when the
    anchor is neutralised. `TIMEOUT` alone pins nothing: it holds either way,
    because the tick that follows the expiry reports it whichever bound the
    resume was given.
    """
    clock = _Clock()
    lead = _profile("lead", max_ticks=3, stop_when="converged")
    store = InMemoryCheckpointStore()
    crashing = _Model({"lead": [_draft(rationale="one"),
                                RuntimeError("crash before tick 3"),
                                _draft(rationale="three")]},
                      on_call=lambda _request: clock.advance(10.0))
    context = _context(deadline_seconds=100.0)
    run_id = context.resolved_run_id("lead")
    runtime = _runtime(crashing, profiles={"lead": lead}, checkpoints=store,
                       clock=clock)
    with pytest.raises(RuntimeError):
        runtime.run("lead", context)

    crashed = store.get(run_id)
    assert crashed is not None and crashed.is_terminal() is False
    assert crashed.deadline_mono == pytest.approx(100.0)

    # The resume's own call costs 95 seconds — more than the 80 it had left.
    resumed = _Model({"lead": [_draft(rationale="two"),
                               _draft(rationale="three"),
                               _draft(rationale="four")]},
                     on_call=lambda _request: clock.advance(95.0))
    again = _runtime(resumed, profiles={"lead": lead}, checkpoints=store,
                     clock=clock).resume(run_id, lease_generation="gen-1")

    assert again.termination == Termination.TIMEOUT.value
    assert again.state == "FAILED"
    # One call, not two: the run spent the carry, not a fresh bound. (A fresh
    # bound would allow a second call and end at tick 4, mono 210.)
    assert resumed.calls_for("lead") == 1
    assert clock.monotonic() == pytest.approx(115.0)
    assert again.ticks == 3


# ═══════════════════════ E5 — an informed retry, a bounded wait ══════════════


def test_a_retry_is_asked_with_the_refusal_that_ended_the_previous_attempt(
        ) -> None:
    """E5, half 1: the retry re-issued the *identical* request.

    The runtime knew why the call was refused and withheld it from the only
    party that could act on it, so attempt 2 could only fail the way attempt 1
    did. The refusal now travels into attempt 2 as origin-marked data.
    """
    lead = _profile("lead", max_ticks=1, max_model_calls_per_tick=2)
    model = _Model({"lead": [
        ModelRefusal(code=RATIONALE, detail="the draft carried no rationale"),
        _draft()]})
    runtime = _runtime(model, profiles={"lead": lead})
    result = runtime.run("lead", _context())

    assert model.calls_for("lead") == 2
    assert result.state == "SUCCEEDED"

    # Attempt 1 is the plain request: no retry note.
    assert _retry_envelopes(model.prompt_for("lead", 0)) == []
    # Attempt 2 carries exactly one, naming the refusal and the attempt it ended.
    notes = _retry_envelopes(model.prompt_for("lead", 1))
    assert len(notes) == 1
    document = json.loads(notes[0].text)
    assert document["code"] == RATIONALE
    assert document["detail"] == "the draft carried no rationale"
    assert document["attempt"] == 1


def test_the_retry_sleep_never_crosses_the_runs_deadline() -> None:
    """E5, half 2: the wait is bounded by the budget *and* by the run's bound.

    The budget alone bounds the schedule (`base * 2**i`); the run's deadline
    bounds it again, because sleeping past the instant the run must stop would
    spend the run's bound on waiting rather than on work.
    """
    clock = _Clock()
    slept: list[float] = []
    supervisor = Supervisor(clock=lambda: STAMP, monotonic=clock.monotonic,
                            sleep=slept.append)

    def always_retryable(_attempt: int) -> ModelRefusal:
        return ModelRefusal(code=RATIONALE, detail="still no rationale")

    # A 3-second bound against a 5-second first delay: the wait would cross it.
    result, attempts = supervisor.attempt(
        always_retryable, retryable=lambda item: True,
        budget=RetryBudget(max_retries=2, base_delay_seconds=5.0),
        deadline=clock.monotonic() + 3.0)

    assert slept == []
    assert attempts == (1,)
    assert isinstance(result, ModelRefusal)

    # With room to spare the schedule runs exactly as the budget declares.
    slept.clear()
    _result, attempts = supervisor.attempt(
        always_retryable, retryable=lambda item: True,
        budget=RetryBudget(max_retries=2, base_delay_seconds=5.0),
        deadline=clock.monotonic() + 1_000.0)
    assert slept == [5.0, 10.0]
    assert attempts == (1, 2, 3)


# ═══════════════════════ E6 — no dead termination vocabulary ═════════════════


def test_the_termination_vocabulary_holds_no_dead_member() -> None:
    """E6: `DELEGATION_LIMIT` was declared and never written by any site.

    The module docstring claimed the delegation depth and child-run budget "stop
    the loop" while the code refused the delegation and carried on. The constant
    is gone and the docstring now states the actual contract; every remaining
    member is reachable, which is what the second half of this pin checks.
    """
    assert "DELEGATION_LIMIT" not in {member.name for member in Termination}

    source = Path(run_module.__file__).read_text(encoding="utf-8")
    for member in Termination:
        assert f"Termination.{member.name}" in source, member.name
    # And the docstring no longer makes the claim the code contradicted.
    assert "child-run budget all stop the loop" not in source


# ═══════════════════════ E7 — one severity rule ══════════════════════════════


def test_a_malformed_tool_call_is_refused_and_the_tick_carries_on() -> None:
    """E7: a shape the model got wrong is data, not a run-ending event.

    A tool call with no `capability_id` used to stop the run while every other
    malformed-output site was benign, with nothing stating which was which.
    """
    lead = _profile("lead", max_ticks=1, capabilities=("source_search",),
                    fields=("proposals", "tool_calls"))
    capabilities = _Capabilities()
    model = _Model({"lead": [_draft(tool_calls=[
        {"arguments": {"query": "x"}}])]})       # no capability_id at all
    runtime = _runtime(model, profiles={"lead": lead},
                       capabilities=capabilities)
    result = runtime.run("lead", _context())

    assert capabilities.requests == []
    assert result.refusal_codes() == ("MALFORMED_PAYLOAD",)
    # The run is not failed by it, and the tick's draft still stands.
    assert result.state == "SUCCEEDED"
    assert result.termination != Termination.TOOL_FAILED.value
    assert [proposal.was_admitted() for proposal in result.proposals] == [True]


def test_a_capability_the_plane_invoked_and_that_failed_still_stops_the_run(
        ) -> None:
    """E7, the other half of the rule: invoked-and-failed is fatal."""
    lead = _profile("lead", max_ticks=1, capabilities=("source_search",),
                    fields=("proposals", "tool_calls"))
    failed = Observation(capability_id="source_search", status="FAILED",
                         failure=FailureKind.TOOL_ERROR, detail="boom")
    model = _Model({"lead": [_draft(tool_calls=[
        {"capability_id": "source_search", "arguments": {"query": "x"}}])]})
    runtime = _runtime(model, profiles={"lead": lead},
                       capabilities=_Capabilities([failed]))
    result = runtime.run("lead", _context())

    assert result.state == "FAILED"
    assert result.termination == Termination.TOOL_FAILED.value


def test_a_capability_refusal_from_the_plane_still_stops_the_run() -> None:
    """E7: a refusal from the plane that actually ran the call is fatal too."""
    lead = _profile("lead", max_ticks=1, capabilities=("source_search",),
                    fields=("proposals", "tool_calls"))
    model = _Model({"lead": [_draft(tool_calls=[
        {"capability_id": "source_search", "arguments": {"query": "x"}}])]})
    runtime = _runtime(
        model, profiles={"lead": lead},
        capabilities=_Capabilities([
            CapabilityRefusal(code="EVIDENCE_REF", detail="no such artifact")]))
    result = runtime.run("lead", _context())

    assert result.state == "FAILED"
    assert result.termination == Termination.TOOL_FAILED.value


# ═══════════════════════ E8 — the provenance link ═══════════════════════════


def test_a_draft_carries_the_evidence_it_was_drafted_on() -> None:
    """E8: `capability_refs` was declared, round-tripped and never written.

    A draft is authored *before* its own tick's capability calls run, so what
    informed it is the evidence the run had already retained — the records the
    prompt carried. The refs are the calls' derived invocation keys, so the link
    is to the exact calls and never to an authored identity.
    """
    lead = _profile("lead", max_ticks=2, stop_when="converged",
                    capabilities=("source_search",),
                    fields=("proposals", "tool_calls"))
    observed = Observation(
        capability_id="source_search", status="OK", payload=None,
        artifacts=("artifacts/observation-1",))
    model = _Model({"lead": [
        _draft(rationale="one", tool_calls=[
            {"capability_id": "source_search", "arguments": {"query": "x"}}]),
        _draft(rationale="two")]})
    runtime = _runtime(model, profiles={"lead": lead},
                       capabilities=_Capabilities([observed]))
    result = runtime.run("lead", _context())

    checkpoint = runtime.checkpoint(result.run_id)
    assert checkpoint is not None
    assert len(checkpoint.feedback) == 1
    expected = tool_idempotency_key_of(result.run_id, 1, 0, "source_search")
    assert checkpoint.feedback[0].invocation_ref == expected

    # Tick 1 drafted before any call ran: nothing had informed it yet.
    assert result.proposals[0].capability_refs == ()
    # Tick 2 drafted on that evidence, and names the exact call.
    assert result.proposals[1].capability_refs == (expected,)


# ═══════════════════════ G8 — the deadline mid-batch ════════════════════════


def test_the_deadline_is_observed_mid_batch_not_only_at_the_tick() -> None:
    """G8 (VALID, minor): the batch read `token.cancelled` and nothing else.

    Every other site in the run goes through the supervisor; this one did not,
    so a batch could keep invoking capabilities past the run's own bound.
    """
    clock = _Clock()
    lead = _profile("lead", max_ticks=1, capabilities=("source_search",),
                    fields=("proposals", "tool_calls"))
    batch = [{"capability_id": "source_search", "arguments": {"query": "a"}},
             {"capability_id": "source_search", "arguments": {"query": "b"}}]
    # The first capability call burns the whole bound; the second must not start.
    capabilities = _Capabilities(
        on_call=lambda _request: clock.advance(1_000.0))
    model = _Model({"lead": [_draft(tool_calls=batch)]})
    runtime = _runtime(model, profiles={"lead": lead},
                       capabilities=capabilities, clock=clock)
    result = runtime.run("lead", _context(deadline_seconds=5.0))

    assert len(capabilities.requests) == 1
    assert result.termination == Termination.TIMEOUT.value


# ═══════════════════════ G8 — the two confirmed non-bugs ════════════════════


def test_a_zero_limit_defers_to_the_profile_rather_than_disabling() -> None:
    """G8 `or`-zero — RECORDED (STALE), not a defect.

    `RunLimits` documents `0`/`None` as "defers to the profile's config", and
    `_max_ticks` reads it that way. `0` is therefore not "disabled", and the
    `or` that the external audit read as conflation is the documented rule.
    """
    assert RunLimits().max_ticks == 0
    lead = _profile("lead", max_ticks=2, stop_when="converged")
    model = _Model({"lead": [_draft(rationale="one"), _draft(rationale="two")]})
    runtime = _runtime(model, profiles={"lead": lead})
    result = runtime.run("lead", _context(max_ticks=0))

    # The context said 0, so the profile's 2 governed — not "no ticks at all".
    assert model.calls_for("lead") == 2
    assert result.ticks == 2


def test_converged_novelty_is_read_before_the_seen_set_absorbs_it() -> None:
    """G8 converged/digest — RECORDED (NOT-A-BUG), confirmed deliberate.

    Novelty is counted against `seen_drafts` *before* the update, so the tick
    that first raises a draft counts it as novel and only a genuine repeat reads
    as `novel == 0`. `draft_digest()` excluding the tick is what lets the same
    draft raised on another tick be recognised as the same draft at all.
    """
    lead = _profile("lead", max_ticks=3, stop_when="converged")
    model = _Model({"lead": [_draft(rationale="same"), _draft(rationale="same"),
                             _draft(rationale="same")]})
    runtime = _runtime(model, profiles={"lead": lead})
    result = runtime.run("lead", _context())

    # Tick 1 is novel; tick 2 repeats it, so the repetition trip ends the run —
    # the same draft, recognised across ticks, which is the digest's job.
    assert result.termination == Termination.STOP_WHEN.value
    assert result.ticks == 2
    assert len({proposal.draft_digest() for proposal in result.proposals}) == 1
