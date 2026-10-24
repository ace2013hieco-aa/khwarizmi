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
- **M2 is `n/a`, never `0.0`.** The composed handler is given no capability
  port, so no tool invocation can reach a recorder. A zero would read as "no
  repeated tool calls" — a claim nobody measured.

`render()` never raises: a collector defect prints `vector: unavailable
(<reason>)` and the run keeps its own exit code (R3).
"""

from __future__ import annotations

from collections.abc import Mapping

from hermes.agents.runtime.config import ProfileSpec
from hermes.agents.runtime.supervisor import Supervisor
from hermes.agents.runtime.types import ProposalSet
from hermes.agents.runtime.wiring import RuntimeWiring
from hermes.eval.loop_metrics import (
    RunObservation,
    prompt_payload_summary,
    termination_mix,
)
from hermes.eval.loop_observations import RecordingModelPort, collect_run

__all__ = ["LiveVector"]

#: How many collected runs a vector line may summarize. The CLI bounds the
#: ledger rows separately; this bound keeps the line one line.
_MAX_RUNS = 64


class LiveVector:
    """Collects each stage run's surfaces, then renders one vector line."""

    def __init__(
        self,
        *,
        supervisor: Supervisor,
        profiles: Mapping[str, ProfileSpec],
        recorder: RecordingModelPort,
    ) -> None:
        self._supervisor = supervisor
        self._profiles = profiles
        self._recorder = recorder
        self._pending: list[tuple[RuntimeWiring, ProposalSet]] = []

    def record(self, wiring: RuntimeWiring, result: ProposalSet) -> None:
        """Retain one stage run's surfaces. Never raises, never reads state."""
        self._pending.append((wiring, result))

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
            f" M2=n/a"
        )
