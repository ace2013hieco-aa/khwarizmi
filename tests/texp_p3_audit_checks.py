"""GR3-P3-reconcile — ADVERSARY independent checks (not a test; not collected).

STATUS: written by the P3-audit pass and retained verbatim as the audit's
evidence. Its `step_convention` block still contrasts the record's
ORIGINAL `steps = 200` against the twin's `budget // 2`; that contrast is
historical — at `gr3-b4/p3-repair` the probe itself now uses the twin's
convention. The numbered list below likewise describes the state the
audit FOUND (SIMPLE-path census, `steps = 200`, every-prefix counting),
all of which the repair pass corrected in the probe; it is not a
description of the repaired probe. The `space_convention` block remains a
live cross-implementation check against the repaired probe.

Originally written from scratch against live source to attack the record's
numbers, not to re-run its script:

1. B4 admissibility — independent scan of every edge type in every fixture
   plus explicit validator calls on length-1 AND length-2 paths.
2. Enumeration convention — the record counts SIMPLE paths (no repeated
   node). The twin's own `kernel.propose` has NO cycle check, so the
   reachable space is WALKS. Count both; a larger walk space means the
   record's coverage is OVERSTATED (flatters the curve).
3. Step-cap sensitivity — the record's chains run `steps=200` over 4
   segments (≈204 evals ceiling). Re-measure coverage with larger
   `steps` and see whether the claimed 100 % crossing (n=32→48) MOVES.
4. Source-set tautology — `documents_touched` vs `sources`.
5. Independent coverage harness (own BudgetCounter loop) vs the record's.

Seed band: PILOT 1000–1005 (already consumed at P4). Read-only.
Run: .venv/Scripts/python.exe tests/texp_p3_audit_checks.py
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
from fixtures import b4_reference_graphs  # noqa: E402
from generator import StrataParams, as_adjacency, generate  # noqa: E402
from kernel import (  # noqa: E402
    BudgetCounter,
    BudgetOverrun,
    ChainConfig,
    initial_path,
    make_rng_stream,
    run_chain,
)
from validator import ADMISSIBLE_SEQUENCES, EDGE_ALPHABET, validate_path  # noqa: E402

L_MAX = 2
#: Proper prefixes (strictly shorter than a table sequence) — the only
#: tuples that can be EXTENDED. (The record's probe used every prefix as a
#: countable path, which admits `refines`/`analogous_to` singletons the
#: validator refuses; see F4.)
PROPER_PREFIXES = frozenset(s[:i] for s in ADMISSIBLE_SEQUENCES
                            for i in range(1, len(s)))
#: The twin harnesses pass steps = budget // 2 (micropilot.py:80-81,
#: pilot.py:90-91 / 135-136); at AUDIT TIME the record's probe passed
#: steps = 200 — that is the historical state this block attacks. The
#: record's probe has since been corrected to `budget // 2` (P3-repair C2);
#: this script is retained verbatim as the audit's evidence.
TWIN_STEPS = lambda b: b // 2  # noqa: E731


def strata(n: int) -> StrataParams:
    return StrataParams(n_nodes=n, n_communities=3, bridge_len=2,
                        noise_rate=0.02, n_hubs=2, n_warp_edges=3)


# ── 1. B4 admissibility, independent ────────────────────────────────────

def check_b4() -> dict:
    out = {"alphabet_size": len(EDGE_ALPHABET),
           "sequence_table_size": len(ADMISSIBLE_SEQUENCES),
           "cites_in_alphabet": "cites" in EDGE_ALPHABET,
           "fixtures": []}
    for g in b4_reference_graphs():
        types = sorted({t for _c, _t2, t in g.edges})
        l1_refused = sum(
            1 for c, t, ty in g.edges
            if not validate_path([{"src": c, "dst": t,
                                   "edge_type": ty}]).accepted)
        # length-2: chain any two fixture edges whose types form a table
        # sequence, then ask the validator (the only way a B4 path could
        # ever be admissible).
        chain_refused = chain_checked = 0
        seqs2 = {s for s in ADMISSIBLE_SEQUENCES if len(s) == 2}
        for c1, t1, ty1 in g.edges:
            for c2, t2, ty2 in g.edges:
                if c2 != t1:
                    continue
                if (ty1, ty2) not in seqs2:
                    continue
                chain_checked += 1
                r = validate_path([{"src": c1, "dst": t1, "edge_type": ty1},
                                   {"src": c2, "dst": t2, "edge_type": ty2}])
                if not r.accepted:
                    chain_refused += 1
        # every emitted type must be cites (independently derived)
        all_cites = sum(1 for _c, _t, ty in g.edges if ty == "cites")
        out["fixtures"].append({
            "fixture_id": g.fixture_id, "edges": len(g.edges),
            "edge_types": types, "all_edges_cites": all_cites == len(g.edges),
            "length1_refused": l1_refused,
            "length2_table_chains_tried": chain_checked,
            "length2_table_chains_refused": chain_refused,
        })
    return out


# ── 2. simple paths vs walks ────────────────────────────────────────────

def count_paths(graph, l_max: int = L_MAX) -> dict:
    """Count REAL validator-admissible paths (full type tuple in the
    table, no prefix-only singletons), stratified by length, under two
    conventions:

    - ``walk``   — revisits allowed (the twin's own `kernel.propose` has
      no cycle check, so this is the space the sampler can actually
      reach and evaluate).
    - ``simple`` — no repeated node.
    """
    adj = as_adjacency(graph)
    simple: dict[int, int] = {}
    walk: dict[int, int] = {}

    def rec(node: str, visited: frozenset[str], types: tuple[str, ...],
            strict: bool) -> None:
        bucket = simple if strict else walk
        for e in adj.get(node, ()):
            nt = types + (e["edge_type"],)
            dst = e["dst"]
            if strict and dst in visited:
                continue  # a simple path may not step onto a visited node
            if nt in ADMISSIBLE_SEQUENCES:
                bucket[len(nt)] = bucket.get(len(nt), 0) + 1
            if len(nt) < l_max and nt in PROPER_PREFIXES:
                rec(dst, visited | {dst}, nt, strict)

    for n in sorted(adj):
        rec(n, frozenset({n}), (), True)
        rec(n, frozenset({n}), (), False)
    return {"simple": simple, "walk": walk,
            "simple_total": sum(simple.values()),
            "walk_total": sum(walk.values())}


# ── 3/5. coverage with a tunable step budget ────────────────────────────

def evals_for(n: int, seed: int, budget: int, steps: int,
              algo_seed: int = 1010) -> int:
    """Own segment loop: one shared BudgetCounter, 4 segments (A1 says 4)."""
    inst = generate(strata(n), seed)
    adj = as_adjacency(inst.graph)
    ctx = SearchContext(graph_id=f"audit-{seed}")
    rng = make_rng_stream(f"audit-{seed}", algo_seed,
                          stream=f"b{budget}-s{steps}")
    init = initial_path(rng, adj, validate_path, L_MAX)
    spec = make_a1(5.0, reference_energy, validate_path, budget=budget,
                   steps=steps, l_max=L_MAX)
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


def main() -> None:
    rep: dict = {"audit": "texp-p3-reconcile-adversary"}
    rep["b4_admissibility"] = check_b4()
    rep["space_convention"] = []
    for n in (24, 32, 48, 120):
        c = count_paths(generate(strata(n), 1000).graph)
        rep["space_convention"].append({"n": n, **c})
    # step-convention sensitivity: the twin passes steps=b//2; the record
    # passes steps=200. Where does the 100% crossing sit under each?
    rep["step_convention"] = []
    for n in (24, 32, 48, 120):
        c = count_paths(generate(strata(n), 1000).graph)
        w = c["walk_total"]  # the space the sampler can actually reach
        row = {"n": n, "true_walk_space": w,
               "true_simple_space": c["simple_total"], "cells": {}}
        for label, steps_of in (("twin_steps_eq_B_over_2", TWIN_STEPS),
                                ("record_steps_eq_200", lambda _b: 200),
                                ("steps_eq_400", lambda _b: 400)):
            for budget in (150, 300):
                e = evals_for(n, 1000, budget, steps_of(budget))
                row["cells"][f"{label}_B{budget}"] = {
                    "steps": steps_of(budget), "evals": e,
                    "coverage_pct": round(100.0 * e / w, 2)}
        rep["step_convention"].append(row)
    print(json.dumps(rep, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
