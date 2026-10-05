"""TEXP-001 S6 — analysis + reporting helpers (Case B, outside src/).

Pure statistics over PLAIN result records (lists/dicts of floats/strings).
Reads result FILES (see :func:`load_results`); never imports generator,
sampler, kernel, validator, energy, or any `hermes.*` module — the
analysis cannot reach back into the machinery it judges. Stdlib only
(`json`, `math`, `random`); bootstrap/Wilcoxon hand-rolled from
caller-seeded RNG (no scipy/numpy — STOP-enforced). Deterministic given
seeds. No model calls, no writes except returning values.

C5 justification (proposed, pending director sign-off — recorded here,
not decreed): the spec powers with two-sided z inside a
(δ_plan − δ_min) superiority-style denominator (D5) but confirms HOLD
on the weaker bar LB > 0 (D6). Either bar may be right, but asymmetric
bars let a marginal EVAL pass get "confirmed" by a HOLD that EVAL
itself would not adopt. PROPOSED resolution: align HOLD to the EVAL
bar (LB > δ_min with point ≥ δ_min) on fresh seeds, keep two-sided
95% CIs (conservative; matches the spec's stated CI method), and
record the choice in the lock. Rationale: symmetric evidentiary
standard for adoption vs confirmation; the weaker HOLD bar answers a
different (sign-only) question than the one D6 asks.

Every output carries the scope-cap stamp (synthetic typed graphs only)
— unscoped numbers are refused by construction (stamp applied inside
each reporter, not left to callers).
"""

from __future__ import annotations

import json
import math
import random
from typing import Any, Mapping, Sequence

SCOPE_STAMP = (
    "synthetic typed graphs only; no claim beyond the tested strata, "
    "no claim about real-graph novelty or LLM-dependent components"
)


def _scope(extra: str = "") -> str:
    return SCOPE_STAMP if not extra else SCOPE_STAMP + " | " + extra


def load_results(path: str) -> list[dict[str, Any]]:
    """Read a result file (JSON list of records). Shape-checked:
    must be a list of mappings, else ValueError (never a silent
    misread). This is the ONLY file input — analysis never touches
    generator/sampler internals."""
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    if not isinstance(data, list) or not all(
            isinstance(r, dict) for r in data):
        raise ValueError(
            f"result file {path!r} must be a JSON list of records")
    return data


def paired_bootstrap_ci(diffs: Sequence[float], n_resamples: int = 10000,
                        alpha: float = 0.05, seed: int = 0,
                        ) -> tuple[float, float]:
    """Percentile bootstrap CI of the mean paired difference (spec D5:
    two-sided 95%, 10,000 resamples). Deterministic given seed. Raises
    ValueError on empty input or non-finite values (fail-closed, never
    a CI over garbage)."""
    vals = list(diffs)
    if not vals:
        raise ValueError("no paired differences supplied")
    if any(not isinstance(v, (int, float)) or not math.isfinite(v)
           for v in vals):
        raise ValueError("paired differences must be finite numbers")
    if n_resamples < 1:
        raise ValueError(f"n_resamples must be >= 1, got {n_resamples!r}")
    rng = random.Random(seed)
    n = len(vals)
    means = sorted(
        sum(vals[rng.randrange(n)] for _ in range(n)) / n
        for _ in range(n_resamples))
    lo_k = min(n_resamples - 1, int((alpha / 2) * n_resamples))
    hi_k = min(n_resamples - 1, int((1 - alpha / 2) * n_resamples))
    return (means[lo_k], means[hi_k])


def wilcoxon_signed_rank(diffs: Sequence[float]) -> dict[str, float]:
    """Hand-rolled Wilcoxon signed-rank (spec D7 sensitivity check).
    Drops zero differences, averages tied ranks. Returns W+/W-/n.
    Pure; no p-value computed anywhere in this module (effect size
    with CI is the estimand — never a p-value alone)."""
    vals = [float(v) for v in diffs]
    nz = [(abs(v), 1 if v > 0 else -1) for v in vals if v != 0.0]
    if not nz:
        return {"W+": 0.0, "W-": 0.0, "n": 0.0}
    ordered = sorted(range(len(nz)), key=lambda i: nz[i][0])
    ranks = [0.0] * len(nz)
    i = 0
    while i < len(nz):
        j = i
        while j + 1 < len(nz) and nz[ordered[j + 1]][0] == nz[ordered[i]][0]:
            j += 1
        avg = (i + j) / 2.0 + 1.0
        for k in range(i, j + 1):
            ranks[ordered[k]] = avg
        i = j + 1
    w_pos = sum(r for (_, s), r in zip(nz, ranks) if s > 0)
    w_neg = sum(r for (_, s), r in zip(nz, ranks) if s < 0)
    return {"W+": w_pos, "W-": w_neg, "n": float(len(nz))}


def methods_agree(diffs: Sequence[float], ci: tuple[float, float]) -> bool:
    """Do bootstrap CI and Wilcoxon point the same direction? Agreement
    = CI excludes 0 on the same side Wilcoxon's majority favors
    (W+ vs W-), or both neutral (CI covers 0 AND W+ == W-). Used by the
    D7 disagreement rule (report both, default to keep-A1)."""
    lo, hi = ci
    w = wilcoxon_signed_rank(diffs)
    if lo > 0:
        return w["W+"] > w["W-"]
    if hi < 0:
        return w["W-"] > w["W+"]
    return w["W+"] == w["W-"]


def decide_outcome(ci: tuple[float, float], guardrails_pass: bool,
                   hold_confirmed: bool, point: float,
                   delta_min: float = 0.05,
                   methods_agree_flag: bool = True) -> int:
    """Spec D6 decision rule (1 adopt / 2 keep / 3 A1-superior), with the
    C5-proposed HOLD alignment documented in the module docstring, plus
    the D7 disagreement default (report both, default to 2) wired in via
    ``methods_agree_flag``. Pure function of its inputs — no hidden
    state. ``hold_confirmed`` is computed by the caller under the
    recorded HOLD bar (see C5 proposal); this function does not smuggle
    in either bar."""
    lo, hi = ci
    if not methods_agree_flag:
        return 2
    if lo > delta_min and guardrails_pass and hold_confirmed:
        return 1
    if hi < -delta_min:
        return 3
    return 2


def evaluate_guardrails(record: Mapping[str, object]) -> dict[str, object]:
    """Guardrail evaluation over a plain record with keys:
    ``g1_violations`` (int, must be 0), ``g2_hub_margin`` /
    ``g3_dup_margin`` (floats, A2-minus-A1 margins, must be <= 0.05),
    ``g4_overhead`` (float, must be <= 1.5), ``g5_determinism`` (bool).
    Returns pass flag + per-guardrail verdicts + scope stamp. Missing
    or misshapen keys fail closed (False, never an exception)."""
    def _num(key: str) -> float | None:
        v = record.get(key)
        return float(v) if isinstance(v, (int, float)) and not isinstance(
            v, bool) and math.isfinite(float(v)) else None

    checks: dict[str, bool] = {}
    g1 = _num("g1_violations")
    checks["G1"] = g1 is not None and g1 == 0
    for key, name, cap in (("g2_hub_margin", "G2", 0.05),
                           ("g3_dup_margin", "G3", 0.05),
                           ("g4_overhead", "G4", 1.5)):
        v = _num(key)
        checks[name] = v is not None and v <= cap
    g5 = record.get("g5_determinism")
    checks["G5"] = g5 is True
    return {"pass": all(checks.values()), "checks": checks,
            "scope": _scope()}


def report_effect(diffs: Sequence[float], ci: tuple[float, float],
                  strata: str = "TBD (B4)") -> dict[str, object]:
    """Effect-size report: mean with CI (never a p-value alone — none
    computed), Wilcoxon direction, agreement flag, scope stamp."""
    vals = list(diffs)
    mean = sum(vals) / len(vals) if vals else 0.0
    w = wilcoxon_signed_rank(vals)
    return {"mean": mean, "ci": list(ci),
            "n": len(vals),
            "wilcoxon": w, "methods_agree": methods_agree(vals, ci),
            "scope": _scope(f"strata: {strata}")}


__all__ = [
    "SCOPE_STAMP",
    "decide_outcome",
    "evaluate_guardrails",
    "load_results",
    "methods_agree",
    "paired_bootstrap_ci",
    "report_effect",
    "wilcoxon_signed_rank",
]
