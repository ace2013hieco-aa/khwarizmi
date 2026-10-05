"""TEXP-001 S6 — lock block tooling (Case B, outside src/).

Canonical serialization + sha256 over the appendix lock block. ALL
fields are "FILL" — filling any field with a real value is P4 work
(STOP-enforced here: `lock_template()` emits FILLs only, and
`assert_all_fill` pins that). Stdlib only (`json`, `hashlib`).
Deterministic: key order invariant under input construction order.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping

FILL = "FILL"


def lock_template() -> dict[str, Any]:
    """The appendix lock block with every fillable field set to FILL.
    Mirrors the spec appendix keys exactly (plus the C5/C7 record slots
    the P1 audit requires at lock: `hold_bar` and `validator_agreement`
    start as FILL like everything else)."""
    return {
        "spec_id": FILL,
        "spec_version": FILL,
        "code_commit": FILL,
        "analysis_script_sha256": FILL,
        "arms": {"A0": FILL, "A1": FILL, "A2": FILL},
        "incumbent": FILL,
        "energy_ref": FILL,
        "validator_ref": FILL,
        "validator_provenance": FILL,
        "strata": {"size": FILL, "bridge_len": FILL, "noise": FILL},
        "K": FILL,
        "budget_B": FILL,
        "seeds": {"PILOT": FILL, "TUNE": FILL, "EVAL": FILL,
                  "HOLD": FILL},
        "R_seeds_per_graph": FILL,
        "N_tune_per_arm": FILL,
        "tuned_hyperparameters": {"A1": FILL, "A2": FILL},
        "primary_metric": FILL,
        "delta_min": FILL,
        "delta_plan": FILL,
        "alpha": FILL,
        "power": FILL,
        "sigma_d_pilot": FILL,
        "N_eval_graphs": FILL,
        "N_hold_graphs": FILL,
        "guardrails": {"G1_violations": FILL, "G2_hub_margin": FILL,
                       "G3_dup_margin": FILL, "G4_overhead_max": FILL,
                       "G5_determinism": FILL},
        "ci_method": FILL,
        "decision_rule": FILL,
        "hold_bar": FILL,
        "validator_agreement": FILL,
    }


def assert_all_fill(block: Mapping[str, Any]) -> list[str]:
    """Return paths of every leaf that is NOT exactly FILL. Empty list
    ⇒ template clean (STOP: filling is P4). Note: even appendix-fixed
    structural constants (strata bridge_len/noise) stay FILL here per
    the STOP rule — P4 restores the appendix values ([2,3,4] /
    [0.02,0.10]) when filling."""
    bad: list[str] = []

    def walk(node: Any, path: str) -> None:
        if isinstance(node, dict):
            for k, v in node.items():
                walk(v, f"{path}.{k}" if path else str(k))
        elif isinstance(node, list):
            for i, v in enumerate(node):
                walk(v, f"{path}[{i}]")
        elif node != FILL:
            bad.append(path)

    walk(block, "")
    return bad


def canonical_lock_block(block: Mapping[str, Any]) -> str:
    """Canonical serialization (sorted keys, compact separators) —
    input construction order cannot change the bytes."""
    return json.dumps(block, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False)


def lock_block_hash(canonical: str) -> str:
    """SHA-256 hex over the canonical serialization (spec D8.4)."""
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


__all__ = [
    "FILL",
    "assert_all_fill",
    "canonical_lock_block",
    "lock_block_hash",
    "lock_template",
]
