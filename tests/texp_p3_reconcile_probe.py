"""TEXP-P3-reconcile — PROBE (not a test; no test_* prefix, not collected).

Read-only reconciliation evidence for `docs/gr3-b4/P3-reconciliation.md`.

REPAIRED at gr3-b4/p3-repair (P3-audit C2/C3/C4): the step budget is now
the TWIN's convention (`steps = budget // 2`, as every twin harness
passes — `micropilot.py:80-81`, `pilot.py:90-91` / `:135-136`), the
enumeration counts real validator-admissible paths rather than table
PREFIXES, the walk/simple distinction is stated instead of mislabelled,
the enumeration cap now FAILS CLOSED, and the scale metadata is truthful.

It answers:

A. What does the B4 handoff actually deliver to the twin read path?
   Consumes every packaged B4 fixture through the twin's own read path
   (`experiments/texp-001/fixtures.py`, B4 SOURCE section, at the twin pin
   `texp-001/s6-audit @ a927c7a`) and reports the graph scale and the
   number of validator-admissible paths each graph yields.

B. What is the twin's own coverage-vs-rank situation, measured on the
   PINNED machinery? Enumerates the admissible path space under BOTH
   conventions (walks, and node-simple paths), then measures the sampled
   budget's coverage of it under the twin's step convention, plus the
   planted bridge's position under the pinned energy.

SCALE SCOPE, stated exactly: micro strata (n ∈ {24, 32, 48}) plus one
PILOT-scale (n=120) enumeration and one bounded chain per budget. The
PILOT grid, TUNE, EVAL and HOLD are NOT executed. Seeds are the
already-consumed PILOT band 1000–1005. No writes, no `src/` import, no
model call. Deterministic.

Run: .venv/Scripts/python.exe tests/texp_p3_reconcile_probe.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TWIN = ROOT / "experiments" / "texp-001"
sys.path.insert(0, str(TWIN))

from arms import make_a1  # noqa: E402
from energy import SearchContext, reference_energy  # noqa: E402
from fixtures import (  # noqa: E402
    B4_EDGE_TYPE,
    b4_available,
    b4_reference_graphs,
)
from generator import StrataParams, as_adjacency, generate  # noqa: E402
from kernel import (  # noqa: E402
    BudgetCounter,
    BudgetOverrun,
    ChainConfig,
    initial_path,
    make_rng_stream,
    run_chain,
)
from validator import (  # noqa: E402
    ADMISSIBLE_SEQUENCES,
    EDGE_ALPHABET,
    validate_path,
)

L_MAX = 2  # the arms' default (`make_a1(..., l_max=2)`); F7 uses the same
BUDGETS = (150, 300, 600)  # the P4 pilot's three budget levels
#: The twin's own step convention: every harness passes `steps = b // 2`
#: (`micropilot.py:80-81`, `pilot.py:90-91`, `pilot.py:135-136`).
TWIN_STEPS = "budget // 2"
#: Extra step policies reported for transparency only (STEP_SENSITIVITY).
FIXED_STEP_POLICIES = (200, 400)
#: Bounded enumeration. FAIL CLOSED on overflow: a truncated space would
#: shrink the coverage denominator and INFLATE coverage (P3-audit F4), so
#: hitting the cap raises instead of reporting a number.
ENUM_CAP = 400_000
#: Proper prefixes — the only tuples that can be extended. (Used to PRUNE,
#: never to count: a prefix is not an admissible path unless its full
#: sequence is in the table; see `enumerate_paths`.)
PROPER_PREFIXES = frozenset(s[:i] for s in ADMISSIBLE_SEQUENCES
                            for i in range(1, len(s)))


class EnumerationCapExceeded(RuntimeError):
    """The bounded enumeration hit ENUM_CAP — refuse rather than publish a
    coverage denominator that is silently too small."""


# ── A. the B4 handoff, consumed through the twin read path ──────────────

def b4_report() -> dict:
    out: dict = {"available": b4_available(),
                 "alphabet_size": len(EDGE_ALPHABET),
                 "sequence_table_size": len(ADMISSIBLE_SEQUENCES),
                 "b4_edge_type": B4_EDGE_TYPE,
                 "cites_in_alphabet": B4_EDGE_TYPE in EDGE_ALPHABET,
                 "fixtures": []}
    if not out["available"]:
        return out
    for g in b4_reference_graphs():
        touching = {r for c, t, _ in g.edges for r in (c, t)}
        outdeg: dict[str, int] = {}
        for c, _t, _ in g.edges:
            outdeg[c] = outdeg.get(c, 0) + 1
        # Every fixture endpoint is a governed document, and a governed
        # document may have no outgoing cite; the mean is therefore taken
        # over the source set. Note: `documents_touching_an_edge` is a
        # SUBSET of `sources` by construction (the reader refuses a
        # non-governed source), so it is reported as a coverage count, not
        # as an independent measurement.
        documents = sorted(set(touching) | set(g.sources))
        deg = [outdeg.get(n, 0) for n in documents]
        admissible = 0
        for c, t, ty in g.edges:  # a single edge is the shortest candidate path
            if validate_path([{"src": c, "dst": t, "edge_type": ty}]).accepted:
                admissible += 1
        out["fixtures"].append({
            "fixture_id": g.fixture_id,
            "digest": g.digest,
            "twin_ref": g.twin_ref,
            "sources": len(g.sources),
            "edges": len(g.edges),
            "documents_touching_an_edge": len(touching),
            "documents_equals_sources_by_construction":
                len(documents) == len(g.sources),
            "max_out_degree": max(deg) if deg else 0,
            "mean_out_degree": round(sum(deg) / len(deg), 4) if deg else 0.0,
            "zero_out_degree_docs": sum(1 for d in deg if d == 0),
            "admissible_single_edge_paths": admissible,
        })
    return out


# ── B. the twin's admissible path space + coverage + planted tie class ──

def enumerate_paths(graph, l_max: int = L_MAX) -> dict:
    """Count REAL validator-admissible paths — a path counts iff its FULL
    edge-type tuple is a member of `ADMISSIBLE_SEQUENCES` (not merely a
    prefix of one), stratified by length. Reported under two conventions:

    - ``walks``   — revisits permitted. This is the space the sampler can
      actually reach and evaluate: `kernel.propose` has no cycle check
      (`kernel.py:114-141`). PRIMARY denominator.
    - ``simple``  — no repeated node. Reported for transparency.

    Raises EnumerationCapExceeded if either count exceeds ENUM_CAP.
    """
    adj = as_adjacency(graph)
    counts = {"walks": {}, "simple": {}}

    def rec(node: str, visited: frozenset[str], types: tuple[str, ...],
            convention: str) -> None:
        bucket = counts[convention]
        strict = convention == "simple"
        for e in adj.get(node, ()):
            nt = types + (e["edge_type"],)
            dst = e["dst"]
            if strict and dst in visited:
                continue  # a node-simple path may not step onto a visitor
            if nt in ADMISSIBLE_SEQUENCES:
                bucket[len(nt)] = bucket.get(len(nt), 0) + 1
                if sum(bucket.values()) > ENUM_CAP:
                    raise EnumerationCapExceeded(
                        f"{convention} enumeration exceeded ENUM_CAP="
                        f"{ENUM_CAP} — refusing to publish a truncated "
                        f"denominator (it would inflate coverage)")
            if len(nt) < l_max and nt in PROPER_PREFIXES:
                rec(dst, visited | {dst}, nt, convention)

    for node in sorted(adj):
        rec(node, frozenset({node}), (), "simple")
        rec(node, frozenset({node}), (), "walks")
    return {
        "walks": {str(k): v for k, v in sorted(counts["walks"].items())},
        "simple": {str(k): v for k, v in sorted(counts["simple"].items())},
        "walks_total": sum(counts["walks"].values()),
        "simple_total": sum(counts["simple"].values()),
    }


def _strata(n_nodes: int) -> StrataParams:
    return StrataParams(n_nodes=n_nodes, n_communities=3, bridge_len=2,
                        noise_rate=0.02, n_hubs=2, n_warp_edges=3)


def _planted(truth):
    return [tuple(p) for p in truth.planted]


def tie_class_report(n_nodes: int, seed: int) -> dict:
    """Where does the planted bridge sit in the admissible space, ordered by
    the PINNED energy? `energy.reference_energy` is `float(len(path))`
    (`energy.py:66`), so every path of the same length scores IDENTICALLY —
    the planted bridge has no rank, only a TIE CLASS. The interval below is
    the honest substitute for a rank number, and tie/K is the K-output
    hazard: a K-output sorted by this energy can return the planted bridge
    only by luck inside its tie class."""
    inst = generate(_strata(n_nodes), seed)
    graph, truth = inst.graph, inst.truth
    space = enumerate_paths(graph)
    planted = _planted(truth)
    ctx = SearchContext(graph_id=f"probe-{seed}")
    scores = [reference_energy(
        [{"src": u, "dst": v, "edge_type": t} for u, v, t in p], ctx)
        for p in planted]
    plen = len(planted[0]) if planted else 0
    walks = {int(k): v for k, v in space["walks"].items()}
    shorter = sum(c for length, c in walks.items() if length < plen)
    tie = walks.get(plen, 0)
    return {
        "n_nodes": n_nodes,
        "seed": seed,
        "nodes": len(graph.nodes),
        "directed_edges": len(graph.edges),
        "admissible_walks_by_len": space["walks"],
        "admissible_walks_total": space["walks_total"],
        "admissible_simple_by_len": space["simple"],
        "admissible_simple_total": space["simple_total"],
        "planted_bridge_len": plen,
        "planted_energy_pinned": scores,
        "planted_type_seq": [t for _u, _v, t in planted[0]] if planted else [],
        "rank_is_undefined_under_pinned_energy": True,
        "planted_tie_class_size": tie,
        "planted_rank_interval_1_indexed": [shorter + 1, shorter + tie],
        "k8_luck_ratio": round(8.0 / tie, 4) if tie else None,
        "planted_is_one_of_walks": f"1/{space['walks_total']}",
    }


def _run_segments(spec, adj, init, rng, ctx) -> int:
    """run_arm's segment loop with the counter HELD HERE, so the exhausted
    shared counter is readable instead of raising out of segment 2 (the
    pinned `run_arm` propagates the initial-eval BudgetOverrun; the twin's
    own harness absorbed it). Same counter, same call sites."""
    counter = BudgetCounter(spec.budget)
    current = list(init)
    for temp in spec.temperatures:
        try:
            r = run_chain(rng, current, adj, spec.validator_fn,
                          spec.energy_fn, ctx, counter,
                          ChainConfig(temperature=temp, budget=spec.budget,
                                      l_max=spec.l_max,
                                      restart_prob=spec.restart_prob,
                                      max_steps=spec.steps_per_segment))
        except BudgetOverrun:
            break
        current = list(r.best_path)
    return counter.used


def _evals(n_nodes: int, seed: int, budget: int, steps: int,
           algo_seed: int = 1010) -> int:
    inst = generate(_strata(n_nodes), seed)
    adj = as_adjacency(inst.graph)
    ctx = SearchContext(graph_id=f"probe-{seed}")
    rng = make_rng_stream(f"probe-{seed}", algo_seed,
                          stream=f"b{budget}-s{steps}")
    init = initial_path(rng, adj, validate_path, L_MAX)
    spec = make_a1(5.0, reference_energy, validate_path, budget=budget,
                   steps=steps, l_max=L_MAX)
    return _run_segments(spec, adj, init, rng, ctx)


def coverage_report(n_nodes: int, seed: int,
                    algo_seed: int = 1010) -> dict:
    """Evaluations spent by a pinned A1 chain vs the enumerable admissible
    space, under the TWIN's step convention (`steps = budget // 2`)."""
    inst = generate(_strata(n_nodes), seed)
    space = enumerate_paths(inst.graph)
    rows = {}
    for budget in BUDGETS:
        steps = budget // 2  # the twin's convention
        used = _evals(n_nodes, seed, budget, steps, algo_seed)
        rows[f"B{budget}"] = {
            "steps": steps,
            "evaluations": used,
            "coverage_pct_of_walks": round(
                100.0 * used / space["walks_total"], 3),
            "coverage_pct_of_simple": round(
                100.0 * used / space["simple_total"], 3),
        }
    return {
        "n_nodes": n_nodes,
        "seed": seed,
        "admissible_walks_total": space["walks_total"],
        "admissible_simple_total": space["simple_total"],
        "by_budget": rows,
    }


def step_sensitivity(n_nodes: int, seed: int) -> dict:
    """The crossing is NOT invariant to `steps` — reported so no reader can
    mistake the twin-convention crossing for a harness-independent fact."""
    inst = generate(_strata(n_nodes), seed)
    w = enumerate_paths(inst.graph)["walks_total"]
    rows = {}
    for policy in ("budget//2", *FIXED_STEP_POLICIES):
        for budget in BUDGETS:
            steps = budget // 2 if policy == "budget//2" else int(policy)
            used = _evals(n_nodes, seed, budget, steps)
            rows[f"{policy}_B{budget}"] = {
                "steps": steps, "evaluations": used,
                "coverage_pct": round(100.0 * used / w, 2)}
    return {"n_nodes": n_nodes, "admissible_walks_total": w, "cells": rows}


def main() -> None:
    report: dict = {
        "probe": "texp-p3-reconcile",
        "scale_scope": (
            "micro strata (24/32/48) plus one PILOT-scale (n=120) "
            "enumeration and one bounded chain per budget; the PILOT grid, "
            "TUNE, EVAL and HOLD are NOT executed"),
        "pilot_grid_executed": False,
        "l_max": L_MAX,
        "budgets": list(BUDGETS),
        "step_convention": TWIN_STEPS,
        "enum_cap": ENUM_CAP,
        "enum_cap_fails_closed": True,
    }
    report["A_b4_handoff"] = b4_report()
    report["B_tie_class"] = [tie_class_report(n, 1000)
                             for n in (24, 32, 48, 120)]
    report["B_coverage_twin_convention"] = [coverage_report(n, 1000)
                                            for n in (24, 32, 48, 120)]
    report["B_step_sensitivity"] = [step_sensitivity(n, 1000)
                                    for n in (24, 32, 48, 120)]
    # replication check: the six declared PILOT graph seeds, n=120, space only
    for s in (1000, 1001, 1002, 1003, 1004, 1005):
        space = enumerate_paths(generate(_strata(120), s).graph)
        report.setdefault("B_pilot_seed_space", []).append({
            "seed": s,
            "admissible_walks_total": space["walks_total"],
            "admissible_walks_by_len": space["walks"],
            "admissible_simple_total": space["simple_total"]})
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
