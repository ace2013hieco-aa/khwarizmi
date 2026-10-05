"""TEXP-001 S5 — generator + fixture acceptance tests.

Run: .venv/Scripts/python.exe -m pytest experiments/texp-001/test_generator.py -q
Deterministic: fixed seeds throughout; no wall-clock, no I/O, no PILOT
execution (micro-scale self-tests only — directional outcomes at scale
belong to the pilot, where B is calibrated per spec D3).

Honesty note (read before "fixing" a red test by seed-hunting): F2/F7
directional inequalities are asserted for MECHANICS (structure,
determinism, range) here, not for direction. Pinning a lucky seed that
makes A1>A0 at micro-scale would prove nothing — the direction is a
pilot-scale claim under B-calibration.
"""

import pytest

from fixtures import (canonical, f1_determinism, f2_null_sanity,
                      f3_label_shuffle, f4_budget, f5_isolation,
                      f6_validator, f7_sensitivity, hub_fraction,
                      pilot_gate)
from generator import (PlantingError, StrataParams, as_adjacency, edge_seq,
                       generate, jaccard, recall_at_k)
from validator import ADMISSIBLE_SEQUENCES, EDGE_ALPHABET, validate_path

P = StrataParams(n_nodes=48, n_communities=3, bridge_len=2, noise_rate=0.02,
                 n_hubs=2, n_warp_edges=3)
SEEDS = (11, 12, 13)
K, B, S = 8, 150, 40


def inst(seed=7):
    return generate(P, seed)


def test_planted_bridge_admissible_and_shaped():
    t = inst().truth
    assert len(t.planted) == 1
    assert len(t.planted[0]) == 2
    types = tuple(e[2] for e in t.planted[0])
    assert types in ADMISSIBLE_SEQUENCES
    assert validate_path(
        [{"src": u, "dst": v, "edge_type": tt} for u, v, tt in t.planted[0]]
    ).accepted


def test_hub_decoys_present_and_high_degree():
    g = inst().graph
    t = inst().truth
    assert len(t.hubs) == 2
    deg = {n: 0 for n in g.nodes}
    for u, v, _ in g.edges:
        deg[u] += 1
    import statistics
    med = statistics.median(deg.values())
    assert all(deg[h] > med for h in t.hubs)


def test_type_violating_shortcuts_rejected():
    t = inst().truth
    assert len(t.violating_edges) == 3
    for u, v, tt in t.violating_edges:
        assert tt not in EDGE_ALPHABET
        assert not validate_path(
            [{"src": u, "dst": v, "edge_type": tt}]).accepted


def test_near_miss_rejected_planted_kept():
    t = inst().truth
    assert len(t.nearmiss) == 1
    nm = t.nearmiss[0]
    assert not validate_path(
        [{"src": u, "dst": v, "edge_type": tt} for u, v, tt in nm]).accepted
    assert nm[:-1] == t.planted[0][:-1]  # admissible prefix shared


def test_planting_fails_closed_two_bounds():
    # Bound 1 (table): no admissible sequence at all -> table message.
    with pytest.raises(PlantingError):
        generate(StrataParams(n_nodes=48, n_communities=3, bridge_len=5,
                              noise_rate=0.02, n_hubs=2, n_warp_edges=3), 7)


def test_planting_multi_midpoint_l3_l4():
    # S5b: table extension + multi-midpoint construction plant ℓ3/ℓ4.
    from validator import validate_path
    for L in (3, 4):
        inst = generate(StrataParams(n_nodes=48, n_communities=3,
                                     bridge_len=L, noise_rate=0.02,
                                     n_hubs=2, n_warp_edges=3), 7)
        assert len(inst.truth.planted) == 1
        path = inst.truth.planted[0]
        assert len(path) == L
        verts = [path[0][0]] + [e[1] for e in path]
        assert len(set(verts)) == L + 1  # all distinct vertices
        assert validate_path(
            [{"src": u, "dst": v, "edge_type": t} for u, v, t in path]
        ).accepted
        # Near-miss still tracks the planted prefix at the new length.
        nm = inst.truth.nearmiss[0]
        assert len(nm) == L and nm[:-1] == path[:-1]
        assert not validate_path(
            [{"src": u, "dst": v, "edge_type": t} for u, v, t in nm]
        ).accepted


def test_strata_recorded_not_executed_at_scale():
    g = inst().graph
    assert (g.strata.n_nodes, g.strata.bridge_len,
            g.strata.noise_rate) == (48, 2, 0.02)
    assert len(g.nodes) == 48  # micro-scale self-test, not a stratum


def test_secrecy_key_scan_and_id_disjointness():
    inst1 = inst()
    # "bridge" is excluded: it collides with the legitimate `bridge_len`
    # parameter name (a field name, not a marker). Everything a sampler
    # can observe is node ids + edge triples — scan exactly that surface.
    observable = list(inst1.graph.nodes) + [v for e in inst1.graph.edges
                                             for v in e]
    for token in ("planted", "label", "truth", "hit", "decoy", "hub"):
        assert not any(token in s for s in observable), token
    # Plantedness is positional (edges exist in-graph), never marked:
    # every planted triple is a graph edge, with no distinguishing flag.
    eset = set(inst1.graph.edges)
    for p in inst1.truth.planted:
        assert all(e in eset for e in p)

    def dict_ids(o, acc):
        if isinstance(o, dict):
            acc.add(id(o))
            for v in o.values():
                dict_ids(v, acc)
        elif isinstance(o, (list, tuple)):
            for v in o:
                dict_ids(v, acc)
        return acc

    assert dict_ids(inst1.truth, set()).isdisjoint(
        dict_ids(inst1.graph, set()))
    adj1 = as_adjacency(inst1.graph)
    adj2 = as_adjacency(inst1.graph)
    assert adj1 == adj2  # same content...
    assert adj1["n0"] is not adj2["n0"]  # ...fresh objects per call
    for edges in adj1.values():
        for e in edges:
            assert set(e) == {"src", "dst", "edge_type"}
            assert all(isinstance(v, str) for v in e.values())


def test_recall_jaccard_units():
    assert recall_at_k([], []) == 0.0
    assert recall_at_k([(( "a", "b", "supports"),)], []) == 0.0
    p = (("a", "b", "supports"), ("b", "c", "supports"))
    assert recall_at_k([p], [p]) == 1.0
    assert recall_at_k([], [p]) == 0.0
    assert jaccard(p, p) == 1.0
    assert 0.0 < jaccard(p, (("a", "b", "supports"),)) < 1.0


def test_f1_byte_identical():
    v = f1_determinism(P, 7)
    assert v.passed and "byte-identical=True" in v.details


def test_f2_mechanics_not_direction():
    v = f2_null_sanity(inst().graph, inst().truth, SEEDS, K, B, S)
    assert v.fixture_id == "F2"
    rec = eval(v.details.split("recalls=")[1])
    assert set(rec) == {"A0", "A1", "A2"}
    assert all(0.0 <= r <= 1.0 for r in rec.values())
    v2 = f2_null_sanity(inst().graph, inst().truth, SEEDS, K, B, S)
    assert (v.passed, v.details) == (v2.passed, v2.details)


def test_f3_moves_labels_graph_unchanged():
    v = f3_label_shuffle(inst().graph, inst().truth, SEEDS, K, B, S)
    assert "labels-moved=True" in v.details
    assert "graph-unchanged=True" in v.details


def test_f4_equal_counters_and_overrun():
    v = f4_budget(inst().graph, 11, B, S)
    assert v.passed
    assert "overrun=True" in v.details


def test_f5_twin_rejected():
    v = f5_isolation()
    assert v.passed, v.details


def test_f6_decoys_refused_planted_kept():
    v = f6_validator(inst().graph, inst().truth)
    assert v.passed, v.details


def test_f7_mechanics_not_direction():
    v = f7_sensitivity(inst().graph, inst().truth, SEEDS, K, B, S)
    assert v.fixture_id == "F7"
    assert "crippled=" in v.details and "a1=" in v.details
    v2 = f7_sensitivity(inst().graph, inst().truth, SEEDS, K, B, S)
    assert (v.passed, v.details) == (v2.passed, v2.details)


def test_pilot_gate_wires_bar_and_hubs():
    rec = {"A0": 0.1, "A1": 0.5, "A2": 0.6}
    hub = {"A0": 0.4, "A1": 0.1, "A2": 0.1}
    ok, det = pilot_gate(rec, hub, 0.2)
    assert ok is True
    assert det["hub_fractions"] == hub  # recorded, not gated
    ok2, _ = pilot_gate(rec, hub, 0.7)
    assert ok2 is False  # bar binds
    paths = [(("a", "b", "supports"), ("b", "h", "supports"))]
    assert hub_fraction(paths, ["h"]) == 1.0
    assert hub_fraction([], ["h"]) == 0.0
