"""TEXP-001 S4 — arms A0/A1/A2 on the UNMODIFIED shared kernel (Case B).

All three arms mount the kernel from ``kernel.py`` exclusively through its
seam (``run_chain`` + ``ChainConfig`` + ``BudgetCounter``); this module
contains no sampler logic of its own and modifies nothing. STIPULATED
reference behavior throughout (no production sampler exists — B1).

- A0: flat-energy kernel walk (proposal-concentrated, NOT uniform over
  edges/paths — K-S4a correction: "uniform walk" was inaccurate), NO
  energy information. Formalized as a flat (constant-zero) energy
  through the SAME counter call sites, so budget accounting is
  identical across arms by construction (same counter, same call
  sites — the STOP-enforced invariant). Flat energy ⇒ every evaluated
  candidate accepts ⇒ temperature is irrelevant (pinned by test: A0
  trajectories identical across dummy T values). Per-segment
  ``budget_used`` is a CUMULATIVE shared-counter reading, not an
  additive per-segment quantity (summing segments double-counts).
- A1: fixed-T Metropolis (temperature constant across segments).
- A2: cooled Metropolis. The kernel is fixed-T ONLY, so the schedule
  lives here as piecewise-constant segments: segment k runs at
  ``T_k = max(T_end, T0 * alpha**k)`` (spec D1 formula with t = segment
  index). Chained via best-path handoff with ONE shared counter, so
  budget continuity holds. The piecewise-vs-continuous gap is disclosed,
  not hidden: finer segments approach per-step cooling at the cost of
  one extra initial-eval per segment (all counted).

Single-variable rule (D1): A1 and A2 share kernel, energy, validator,
graph, budget mechanics, restart policy, and L_max; they differ ONLY in
the temperature sequence. The ``ArmSpec`` dataclass makes this
mechanical: A1/A2 specs compare equal modulo ``temperatures`` (pinned
by test). Energies stay in-memory floats (K-S2c); nothing is written.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Mapping, Sequence

from kernel import BudgetCounter, ChainConfig, ChainResult, run_chain

Edge = Mapping[str, object]
Graph = Mapping[str, Sequence[Edge]]
ValidatorFn = Callable[[Sequence[Edge]], object]
EnergyFn = Callable[[Sequence[Edge], object], float]


def flat_energy(path: Sequence[Edge], context: object) -> float:
    """A0's energy: the constant function (zero information). NOT a
    measurement — the formalization of 'no energy' inside shared-kernel
    mechanics. Because every candidate evaluates equal, Metropolis
    accepts everything and temperature cannot influence the walk."""
    _ = (path, context)
    return 0.0


@dataclass(frozen=True, slots=True)
class ArmSpec:
    """One arm's full configuration. A1-vs-A2 single-variable check is a
    field-wise comparison of two specs (see tests): equal except
    ``temperatures``."""

    arm_id: str  # "A0" | "A1" | "A2"
    temperatures: tuple[float, ...]  # per-segment T; A0/A1 constant
    energy_fn: EnergyFn
    validator_fn: ValidatorFn
    restart_prob: float
    l_max: int
    budget: int
    steps_per_segment: int


def _check_positive(value: float, name: str) -> float:
    if not value > 0:
        raise ValueError(f"{name} must be > 0, got {value!r}")
    return value


def make_a0(validator: ValidatorFn, restart_prob: float = 0.0,
            l_max: int = 2, budget: int = 500, steps: int = 200,
            n_segments: int = 4) -> ArmSpec:
    """A0 null arm: flat energy (no information), dummy constant
    temperature (provably irrelevant — tested)."""
    if n_segments < 1:
        raise ValueError(f"n_segments must be >= 1, got {n_segments!r}")
    return ArmSpec(
        arm_id="A0", temperatures=(1.0,) * n_segments, energy_fn=flat_energy,
        validator_fn=validator, restart_prob=restart_prob, l_max=l_max,
        budget=budget,
        steps_per_segment=max(1, steps // n_segments))


def make_a1(temperature: float, energy: EnergyFn, validator: ValidatorFn,
            restart_prob: float = 0.0, l_max: int = 2, budget: int = 500,
            steps: int = 200, n_segments: int = 4) -> ArmSpec:
    """A1 incumbent: ONE temperature across all segments (no schedule —
    all-equal temperatures pinned by test; schedule in A1 is STOP)."""
    _check_positive(temperature, "temperature")
    if n_segments < 1:
        raise ValueError(f"n_segments must be >= 1, got {n_segments!r}")
    return ArmSpec(
        arm_id="A1", temperatures=(temperature,) * n_segments,
        energy_fn=energy, validator_fn=validator, restart_prob=restart_prob,
        l_max=l_max, budget=budget,
        steps_per_segment=max(1, steps // n_segments))


def make_a2(t0: float, alpha: float, t_end: float, energy: EnergyFn,
            validator: ValidatorFn, restart_prob: float = 0.0,
            l_max: int = 2, budget: int = 500, steps: int = 200,
            n_segments: int = 4) -> ArmSpec:
    """A2 challenger: piecewise-constant cooling,
    ``T_k = max(t_end, t0 * alpha**k)`` per segment (spec D1 formula).
    Requires 0 < alpha < 1 and positive bounds (else ValueError)."""
    _check_positive(t0, "t0")
    _check_positive(t_end, "t_end")
    if not 0.0 < alpha < 1.0:
        raise ValueError(f"alpha must be in (0, 1), got {alpha!r}")
    if n_segments < 1:
        raise ValueError(f"n_segments must be >= 1, got {n_segments!r}")
    return ArmSpec(
        arm_id="A2",
        temperatures=tuple(max(t_end, t0 * alpha ** k)
                           for k in range(n_segments)),
        energy_fn=energy, validator_fn=validator, restart_prob=restart_prob,
        l_max=l_max, budget=budget,
        steps_per_segment=max(1, steps // n_segments))


def run_arm(spec: ArmSpec, graph: Graph, initial: Sequence[Edge], rng: object,
            context: object) -> list[ChainResult]:
    """Execute one arm: chain segments at the spec's temperatures, handing
    each segment's best path to the next, sharing ONE counter (budget
    continuity across segments). Returns per-segment results; callers
    aggregate. Deterministic given (spec, graph, initial, rng)."""
    counter = BudgetCounter(spec.budget)
    current = list(initial)
    out: list[ChainResult] = []
    for temp in spec.temperatures:
        result = run_chain(
            rng, current, graph, spec.validator_fn, spec.energy_fn,
            context, counter,
            ChainConfig(temperature=temp, budget=spec.budget,
                        l_max=spec.l_max, restart_prob=spec.restart_prob,
                        max_steps=spec.steps_per_segment))
        out.append(result)
        current = list(result.best_path)
    return out


__all__ = [
    "ArmSpec",
    "EnergyFn",
    "Graph",
    "Edge",
    "ValidatorFn",
    "flat_energy",
    "make_a0",
    "make_a1",
    "make_a2",
    "run_arm",
]
