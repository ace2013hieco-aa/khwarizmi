"""The live-run vector sink (OPS-1 R3).

`loop_observations` collects one run's surfaces; a live `hermes run` drives
several runtime runs (one per methodology stage) under a controller tick loop.
Those surfaces do not survive `ctrl.run`, so the composed handler hands each
stage's `(wiring, result)` here **while the run is in flight**, and the CLI asks
for the vector **after** the loop ends. Nothing is computed inside a tick, and
the sink writes nothing: it holds references, then reads.

The three honesty rules this module inherits from `loop_observations`:

- **M0 is the supervisor's own digest** — read, never recomputed, so the trace
  stays the trace's claim.
- **M1 is measured at the port**, by `RecordingModelPort`, which the composition
  injects into the runtime; the recorder is the only path to the model.
- **M2 is measured when a capability port exists.** The composed handler is
  given one `RecordingCapabilityPort` per run, so a zero-call run reports a
  measured ``0.000``; `n/a` survives only where the composition held no port
  at all (a caller that built its own wiring).

`render()` never raises: a collector defect prints `vector: unavailable
(<reason>)` and the run keeps its own exit code (R3).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from hermes.agents.runtime.config import ProfileSpec
from hermes.agents.runtime.supervisor import Supervisor
from hermes.agents.runtime.types import ProposalSet
from hermes.agents.runtime.wiring import RuntimeWiring
from hermes.eval.loop_metrics import (
    RunObservation,
    prompt_payload_summary,
    repeat_tool_rate,
    termination_mix,
)
from hermes.eval.loop_observations import (
    RecordingCapabilityPort,
    RecordingModelPort,
    collect_run,
)

__all__ = ["LiveVector", "StageRunSnapshot"]

#: How many collected runs a vector line may summarize. The CLI bounds the
#: ledger rows separately; this bound keeps the line one line.
_MAX_RUNS = 64


@dataclass(frozen=True, slots=True)
class StageRunSnapshot:
    """One stage run retained for the diagnostic report (OPS-10).

    ``stage`` is the methodology stage kind read from the run's checkpoint
    context; ``result`` is the runtime's own ``ProposalSet``. The report reads
    these; nothing here is an authority.
    """

    stage: str
    result: ProposalSet


class LiveVector:
    """Collects each stage run's surfaces, then renders one vector line."""

    def __init__(
        self,
        *,
        supervisor: Supervisor,
        profiles: Mapping[str, ProfileSpec],
        recorder: RecordingModelPort,
        capabilities: RecordingCapabilityPort | None = None,
    ) -> None:
        self._supervisor = supervisor
        self._profiles = profiles
        self._recorder = recorder
        self._capabilities = capabilities
        self._pending: list[tuple[RuntimeWiring, ProposalSet]] = []

    def record(self, wiring: RuntimeWiring, result: ProposalSet) -> None:
        """Retain one stage run's surfaces. Never raises, never reads state."""
        self._pending.append((wiring, result))

    def stage_runs(self) -> tuple[StageRunSnapshot, ...]:
        """The retained stage runs, with the stage kind from each checkpoint.

        Read-only and pure with respect to the run: the OPS-10 report asks for
        the stage label, the run's own ``ProposalSet`` already carries profile,
        task, state, termination and refusals. A checkpoint that is absent or
        carries no stage falls back to the task-id suffix the projection used.
        """
        snapshots: list[StageRunSnapshot] = []
        for wiring, result in self._pending:
            stage = ""
            checkpoint = wiring.checkpoint(result.run_id)
            if checkpoint is not None:
                payload = checkpoint.context.get("payload")
                if isinstance(payload, Mapping):
                    stage = str(payload.get("stage", ""))
            if not stage and ":" in result.task_id:
                stage = result.task_id.rsplit(":", 1)[-1]
            snapshots.append(StageRunSnapshot(stage=stage, result=result))
        return tuple(snapshots)

    def render(self) -> str:
        """The one-line vector, or `vector: unavailable (<reason>)`."""
        try:
            return self._render()
        except Exception as exc:  # noqa: BLE001 — R3: never fail the run
            return f"vector: unavailable ({type(exc).__name__}: {exc})"

    # ── internals ──

    def _render(self) -> str:
        if not self._pending:
            return "vector: unavailable (no runtime run reached the collector)"
        runs: list[RunObservation] = []
        for wiring, result in self._pending[:_MAX_RUNS]:
            checkpoint = wiring.checkpoint(result.run_id)
            if checkpoint is None:
                continue
            runs.append(collect_run(
                checkpoint=checkpoint,
                supervisor=self._supervisor,
                profiles=self._profiles,
                is_root=True,
                result=result,
            ))
        if not runs:
            return "vector: unavailable (no terminal checkpoint to collect)"
        m1 = prompt_payload_summary(self._recorder.calls)
        mix = termination_mix(runs)
        mix_text = "/".join(f"{name}:{count}" for name, count in mix.items())
        return (
            f"vector: runs={len(runs)}"
            f" admitted={sum(run.admitted for run in runs)}"
            f" duplicate={sum(run.duplicate for run in runs)}"
            f" intent_refused={sum(run.intent_refused for run in runs)}"
            f" other={sum(run.other_refusals for run in runs)}"
            f" mix={mix_text}"
            f" M1(calls={m1['calls']},min={m1['min']:g},"
            f"med={m1['median']:g},max={m1['max']:g})"
            f" {self._m2_text()}"
        )

    def _m2_text(self) -> str:
        """M2 as a number when a recorder was actually in the call path.

        ``0.000`` is a measurement of zero calls, not a silent default; the
        ``n/a`` branch exists only for a composition that held no capability
        port at all (the pre-5B live path and non-live callers).
        """
        if self._capabilities is None:
            return "M2=n/a (no capability port on this run)"
        calls = self._capabilities.calls
        return (f"M2(calls={len(calls)},"
                f"repeat={repeat_tool_rate(calls):.3f})")
