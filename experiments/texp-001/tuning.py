"""TEXP-001 S4 — tuning harness (mechanics only; NO tuning runs here).

Random-search harness per spec D3: N_tune configs per arm sampled over
declared ranges, selection metric = primary metric, robustness fraction
within 0.05 of best. This module is pure config math + selection rules:
it never invokes samplers, energies, or chains, never touches the
kernel/arms modules (importing them would risk accidental TUNE
execution — pinned by test), and uses only caller-seeded RNG. Ranges
are REQUIRED input (declared at lock per D3), never defaulted here —
no numeric range in this file may be mistaken for a declared range.
TUNE execution happens at P4, not here.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Sequence

#: Default trial count per arm (spec D3).
N_TUNE_DEFAULT = 60

#: Robustness margin: fraction of configs within this of best (spec D3).
ROBUSTNESS_MARGIN = 0.05


@dataclass(frozen=True, slots=True)
class TuningSpace:
    """One arm's declared search space. ``ranges`` maps hyperparameter
    name to an INCLUSIVE (lo, hi) interval; values are sampled uniform.
    Provided at lock time — never invented here."""

    arm_id: str
    ranges: Mapping[str, tuple[float, float]]
    n_configs: int = N_TUNE_DEFAULT


def sample_configs(rng: object, space: TuningSpace) -> list[dict[str, float]]:
    """Deterministically enumerate ``n_configs`` configs over the space
    (caller-seeded RNG; same seed + space ⇒ identical list). Raises
    ValueError on empty ranges or non-positive n_configs."""
    if space.n_configs < 1:
        raise ValueError(
            f"n_configs must be >= 1, got {space.n_configs!r}")
    if not space.ranges:
        raise ValueError("ranges must be non-empty (declared at lock)")
    names = sorted(space.ranges)
    out: list[dict[str, float]] = []
    for _ in range(space.n_configs):
        cfg: dict[str, float] = {}
        for name in names:
            lo, hi = space.ranges[name]
            if not lo <= hi:
                raise ValueError(
                    f"range for {name!r} must satisfy lo <= hi, "
                    f"got {(lo, hi)!r}")
            cfg[name] = lo + rng.random() * (hi - lo)  # type: ignore[union-attr]
        out.append(cfg)
    return out


def select_best(scored: Sequence[tuple[dict[str, float], float]]
                ) -> dict[str, float]:
    """Selection metric = primary metric (spec D3): highest score wins;
    ties keep the FIRST (deterministic, documented). Empty input raises
    (no silent default)."""
    if not scored:
        raise ValueError("no scored configs to select from")
    best_cfg, best_score = scored[0]
    for cfg, score in scored[1:]:
        if score > best_score:
            best_cfg, best_score = cfg, score
    return dict(best_cfg)


def robustness_fraction(scores: Sequence[float]) -> float:
    """Fraction of configs within ROBUSTNESS_MARGIN of best (spec D3).
    Empty input returns 0.0 (documented, never NaN)."""
    if not scores:
        return 0.0
    best = max(scores)
    close = sum(1 for s in scores if best - s <= ROBUSTNESS_MARGIN)
    return close / len(scores)


__all__ = [
    "N_TUNE_DEFAULT",
    "ROBUSTNESS_MARGIN",
    "TuningSpace",
    "robustness_fraction",
    "sample_configs",
    "select_best",
]
