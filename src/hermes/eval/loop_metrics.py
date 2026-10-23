"""LOOP-M metrics — pure computation over the loop's observable surfaces.

This module measures the runtime from the outside. It imports no runtime
module and performs no I/O, clock read, DB access, or model call: callers
hand it immutable observations they already collected (the scripted model's
requests, the capability port's invocations, the run's ``ProposalSet``,
checkpoint, and supervisor trace). Nothing here changes a run.

The vector (no composite "quality score" is defined; a weighted number
would hide the trade-offs this baseline exists to expose):

M1 ``prompt_payload_bytes``
    Per model call, the UTF-8 byte length of every prompt envelope's
    ``text`` whose origin is not ``runtime.tick``. Origin/ref metadata and
    the tick marker are markers, not payload; they are counted separately.
    The scenario summary is min / median / max over all model calls in the
    scenario (parent, reviewer, and child calls included).

M2 ``repeat_tool_rate``
    Calls whose ``(capability_id, arguments_digest)`` was already issued in
    the same scenario, divided by the total number of actual capability
    invocations. A malformed call the runtime refuses before invoking is not
    a tool call here; the capability port never saw it.

M3 ``evidence_novelty``
    Per tick, the number of ``ToolFeedback.evidence_digest()`` identities not
    seen in an earlier tick of that run. ``ticks_to_stability`` is the first
    tick that introduced no new identity after the run had accumulated at
    least one; ``None`` when no such tick exists (or the run never observed
    evidence). It is computed from the terminal checkpoint's feedback.

M4 ``review_rounds``
    Consumed review verdicts versus the profile's declared
    ``max_review_rounds``, plus the verdict sequence (``PASS``/``FAIL``).

M5 ``termination_mix``
    Counts of ``SUCCEEDED``, ``TOOL_FAILED``, ``TIMEOUT`` and ``CANCELLED``
    across every run in the corpus. A run whose state/termination falls
    outside that closed set is counted in ``OTHER`` so it cannot disappear;
    the baseline corpus is expected to report ``OTHER == 0``.

M6 ``admitted_proposals``
    Per run: admitted intents, duplicates, intent refusals, and other runtime
    refusals. Admitted counts only ``ADMITTED`` (a duplicate is durable output
    already present, reported separately).

M0 ``trace_digest``
    ``Supervisor.trace_digest(run_id)`` for each run, recorded verbatim. It
    proves the observation is replayable; it is not authority or validity.
"""
from __future__ import annotations

import statistics
from dataclasses import dataclass
from typing import Iterable

__all__ = [
    "PromptCall",
    "RunObservation",
    "ScenarioObservation",
    "ToolCall",
    "aggregate_metrics",
    "prompt_payload_summary",
    "repeat_tool_rate",
    "scenario_metrics",
    "termination_mix",
    "ticks_to_stability",
]


@dataclass(frozen=True, slots=True)
class PromptCall:
    """One model request, measured without its payload text being retained.

    ``payload_bytes`` is the M1 numerator. ``marker_bytes`` is the tick text
    plus the origin/ref labels the router attaches to every envelope; the two
    are separated so the baseline cannot inflate content with envelope
    bookkeeping. ``total_bytes`` is their sum (UTF-8 text plus labels).
    """

    payload_bytes: int
    marker_bytes: int
    total_bytes: int


@dataclass(frozen=True, slots=True)
class ToolCall:
    """One actual capability invocation, identified by derived content."""

    capability_id: str
    arguments_digest: str


@dataclass(frozen=True, slots=True)
class RunObservation:
    """One run's immutable, externally collected facts."""

    run_id: str
    profile: str
    is_root: bool
    state: str
    termination: str
    ticks: int
    trace_digest: str
    admitted: int = 0
    duplicate: int = 0
    intent_refused: int = 0
    other_refusals: int = 0
    review_rounds: int = 0
    review_cap: int = 0
    review_verdicts: tuple[str, ...] = ()
    tick_new_evidence: tuple[int, ...] = ()


@dataclass(frozen=True, slots=True)
class ScenarioObservation:
    """One scenario: its runs plus scenario-level prompt and tool records."""

    scenario_id: str
    runs: tuple[RunObservation, ...]
    prompt_calls: tuple[PromptCall, ...]
    tool_calls: tuple[ToolCall, ...]


def repeat_tool_rate(calls: Iterable[ToolCall]) -> float:
    """Repeated ``(capability_id, arguments_digest)`` / total calls.

    The first occurrence is not a repeat; an empty sequence has rate 0.0.
    """
    ordered = tuple(calls)
    seen: set[tuple[str, str]] = set()
    repeats = 0
    for call in ordered:
        key = (call.capability_id, call.arguments_digest)
        if key in seen:
            repeats += 1
        seen.add(key)
    return (repeats / len(ordered)) if ordered else 0.0


def prompt_payload_summary(calls: Iterable[PromptCall]) -> dict[str, float]:
    """Min / median / max M1 payload bytes across calls (median: arithmetic)."""
    values = [call.payload_bytes for call in calls]
    if not values:
        return {"calls": 0, "min": 0, "median": 0, "max": 0}
    return {
        "calls": len(values),
        "min": min(values),
        "median": statistics.median(values),
        "max": max(values),
    }


def ticks_to_stability(tick_new_evidence: Iterable[int]) -> int | None:
    """First tick with no new evidence after evidence exists, or ``None``.

    A run that never observed evidence (no tick accumulated anything) has no
    stability point: absence of evidence is not convergence.
    """
    accumulated = 0
    for tick, fresh in enumerate(tick_new_evidence, start=1):
        accumulated += fresh
        if accumulated > 0 and fresh == 0:
            return tick
    return None


def termination_mix(runs: Iterable[RunObservation]) -> dict[str, int]:
    """Count the closed termination set; ``OTHER`` is a visible guard."""
    mix = {"SUCCEEDED": 0, "TOOL_FAILED": 0, "TIMEOUT": 0, "CANCELLED": 0,
           "OTHER": 0}
    for run in runs:
        if run.termination in ("TOOL_FAILED", "TIMEOUT", "CANCELLED"):
            mix[run.termination] += 1
        elif run.state == "SUCCEEDED":
            mix["SUCCEEDED"] += 1
        else:
            mix["OTHER"] += 1
    return mix


def scenario_metrics(observation: ScenarioObservation) -> dict:
    """The full M0-M6 vector for one scenario (root row + child accounting)."""
    root = next(run for run in observation.runs if run.is_root)
    children = tuple(run for run in observation.runs if not run.is_root)
    return {
        "scenario": observation.scenario_id,
        "run_id": root.run_id,
        "trace_digest": root.trace_digest,
        "state": root.state,
        "termination": root.termination,
        "ticks": root.ticks,
        "prompt": prompt_payload_summary(observation.prompt_calls),
        "tool_calls": len(observation.tool_calls),
        "repeat_tool_rate": repeat_tool_rate(observation.tool_calls),
        "tick_new_evidence": root.tick_new_evidence,
        "ticks_to_stability": ticks_to_stability(root.tick_new_evidence),
        "review_rounds": root.review_rounds,
        "review_cap": root.review_cap,
        "review_verdicts": root.review_verdicts,
        "admitted": root.admitted,
        "duplicate": root.duplicate,
        "intent_refused": root.intent_refused,
        "other_refusals": root.other_refusals,
        "child_runs": len(children),
        "child_admitted": sum(run.admitted for run in children),
        "child_intent_refused": sum(run.intent_refused for run in children),
        "child_trace_digests": tuple(run.trace_digest for run in children),
        "child_termination_mix": termination_mix(children),
    }


def aggregate_metrics(
    observations: Iterable[ScenarioObservation],
) -> dict:
    """Per-scenario vectors plus corpus-level run totals and termination mix."""
    scenarios = [scenario_metrics(item) for item in observations]
    all_runs = [run for item in observations for run in item.runs]
    return {
        "scenarios": scenarios,
        "runs": len(all_runs),
        "admitted": sum(run.admitted for run in all_runs),
        "duplicate": sum(run.duplicate for run in all_runs),
        "intent_refused": sum(run.intent_refused for run in all_runs),
        "other_refusals": sum(run.other_refusals for run in all_runs),
        "termination_mix": termination_mix(all_runs),
    }
