"""TEXP-001 S5 — benchmark generator (DCSBM-lite, Case B, outside src/).

Generates synthetic typed graphs with a planted bridge plus all three D2
decoy classes. STIPULATED reference behavior throughout (no real graph
exists — B4). Pure, deterministic given seed; stdlib-only
(``dataclasses``, ``random``); no model calls, no I/O, no writes.

Label secrecy BY CONSTRUCTION (not convention): the stored graph holds
edge TRIPLES ``(src, dst, edge_type)`` only — no mappings, no label
keys, no truth linkage. Ground truth is a separate object holding
tuples/strings/numbers exclusively, so no shared mutable reference can
exist between graph and truth (pinned by test: recursive key scan +
id-disjointness). Sampler-facing API (`as_adjacency`) builds fresh
edge dicts per call.

Background typing is supports-dominated BY DESIGN (documented): the S1
sequences table admits short supports paths, so chains keep moving at
fixture scale; noise retypes a fraction of edges (natural near-misses).
Pilot with an extended table uses richer typing.

Fail-closed planting: bridge length ℓ with no admissible sequence in
the S1 table raises ``PlantingError`` (ℓ≥3 today) instead of planting
an unrecallable bridge that would poison recall metrics.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Mapping, Sequence

from validator import ADMISSIBLE_SEQUENCES, EDGE_ALPHABET

#: Marker type for explicit type-violating decoy edges. NEVER in the
#: alphabet by construction (asserted at import); fixture-only.
UNKNOWN_TYPE = "warp"

#: Background edge type (keeps chains moving under the minimal table).
BASE_TYPE = "supports"

assert UNKNOWN_TYPE not in EDGE_ALPHABET
assert BASE_TYPE in EDGE_ALPHABET


class PlantingError(ValueError):
    """Requested bridge cannot be planted admissibly (no table sequence
    of length ℓ) — fail closed instead of poisoning recall."""


@dataclass(frozen=True, slots=True)
class StrataParams:
    """D2 strata knobs. Placeholders per spec (real scale pending B4);
    recorded on every instance."""

    n_nodes: int = 48
    n_communities: int = 3
    bridge_len: int = 2
    noise_rate: float = 0.02
    n_hubs: int = 2
    n_warp_edges: int = 3


@dataclass(frozen=True, slots=True)
class GeneratedGraph:
    """Sampler-visible graph: node ids + edge triples ONLY. No mappings,
    no labels, no truth linkage — structurally incapable of carrying
    planted markers."""

    nodes: tuple[str, ...]
    edges: tuple[tuple[str, str, str], ...]  # (src, dst, edge_type)
    strata: StrataParams
    seed: int


@dataclass(frozen=True, slots=True)
class GroundTruth:
    """Held by fixtures/analysis ONLY — never passed to sampler or
    energy callables. Tuples/strings/numbers exclusively (no mappings,
    hence no shared references with graph objects possible)."""

    planted: tuple[tuple[tuple[str, str, str], ...], ...]
    hubs: tuple[str, ...]
    violating_edges: tuple[tuple[str, str, str], ...]
    nearmiss: tuple[tuple[tuple[str, str, str], ...], ...]
    strata: StrataParams
    seed: int


@dataclass(frozen=True, slots=True)
class BenchmarkInstance:
    graph: GeneratedGraph
    truth: GroundTruth


def as_adjacency(graph: GeneratedGraph) -> dict[str, list[dict[str, str]]]:
    """Build FRESH edge dicts per call (kernel/S1 shape). Never returns
    shared references — each call allocates anew."""
    adj: dict[str, list[dict[str, str]]] = {n: [] for n in graph.nodes}
    for src, dst, etype in graph.edges:
        adj[src].append({"src": src, "dst": dst, "edge_type": etype})
    return adj


def _communities(rng: random.Random, nodes: list[str], n_comm: int,
                 ) -> dict[str, int]:
    order = list(nodes)
    rng.shuffle(order)
    return {n: i % n_comm for i, n in enumerate(order)}


def generate(params: StrataParams, seed: int) -> BenchmarkInstance:
    """Build one benchmark instance. Deterministic in (params, seed)."""
    rng = random.Random(seed)
    nodes = [f"n{i}" for i in range(params.n_nodes)]
    comm = _communities(rng, nodes, params.n_communities)
    theta = {n: 1.0 + rng.paretovariate(2.0) for n in nodes}
    mean_t = sum(theta.values()) / len(nodes)
    in_d, cross_d = 0.10, 0.008
    edges: set[tuple[str, str, str]] = set()
    for i, u in enumerate(nodes):
        for v in nodes[i + 1:]:
            dens = in_d if comm[u] == comm[v] else cross_d
            p = min(1.0, dens * theta[u] * theta[v] / (mean_t * mean_t))
            if rng.random() < p:
                edges.add((u, v, BASE_TYPE))
                edges.add((v, u, BASE_TYPE))
    # Noise: retype a fraction (natural near-misses; may break sequences).
    alpha = sorted(EDGE_ALPHABET)
    edge_list = sorted(edges)
    n_noise = int(len(edge_list) * params.noise_rate)
    for idx in rng.sample(range(len(edge_list)), min(n_noise, len(edge_list))):
        u, v, _ = edge_list[idx]
        edges.discard((u, v, edge_list[idx][2]))
        edges.add((u, v, rng.choice(alpha)))
    # Degrees pre-plant (ordinary-degree rule for intermediates).
    deg: dict[str, int] = {n: 0 for n in nodes}
    for u, v, _ in edges:
        deg[u] += 1
    import statistics
    med = statistics.median(deg.values())
    # Planted bridge across two communities, admissible sequence required.
    seqs = sorted(s for s in ADMISSIBLE_SEQUENCES if len(s) == params.bridge_len)
    if not seqs:
        raise PlantingError(
            f"no admissible sequence of length {params.bridge_len} in the "
            f"S1 table — extend the table before planting this stratum")
    comms = sorted(set(comm.values()))
    ci, cj = comms[0], comms[1 % len(comms)]
    cand_i = [n for n in nodes if comm[n] == ci]
    cand_j = [n for n in nodes if comm[n] == cj]
    rng.shuffle(cand_i)
    rng.shuffle(cand_j)
    seq = seqs[0]
    planted: tuple[tuple[str, str, str], ...] | None = None
    for a in cand_i:
        if deg[a] > med:
            continue
        for b in cand_j:
            if deg[b] > med:
                continue
            # Multi-midpoint (S5b): L-1 distinct intermediates, same
            # ordinary-degree + endpoint-community rule as len-2,
            # generalized. Sampled (not first-found) so bridge placement
            # varies with seed; deterministic given rng state.
            pool = [n for n in nodes
                    if comm[n] in (ci, cj) and deg[n] <= med
                    and n != a and n != b]
            if len(pool) < params.bridge_len - 1:
                continue
            mids = rng.sample(pool, params.bridge_len - 1)
            verts = [a, *mids, b]
            planted = tuple((verts[i], verts[i + 1], seq[i])
                            for i in range(params.bridge_len))
            break
        if planted is not None:
            break
    if planted is None:
        raise PlantingError("no ordinary-degree endpoint pair found")
    for e in planted:
        edges.add(e)
        edges.add((e[1], e[0], e[2]))
    # Hubs: top-degree nodes post-plant (truth only).
    full_deg: dict[str, int] = {n: 0 for n in nodes}
    for u, v, _ in edges:
        full_deg[u] += 1
    hubs = tuple(sorted(nodes, key=lambda n: (-full_deg[n], n))
                 [:params.n_hubs])
    # Explicit type-violating shortcuts (unknown-type cross edges).
    cross = [(u, v) for u in nodes for v in nodes
             if u < v and comm[u] != comm[v]
             and (u, v, UNKNOWN_TYPE) not in edges]
    rng.shuffle(cross)
    violating: list[tuple[str, str, str]] = []
    for u, v in cross[:params.n_warp_edges]:
        edges.add((u, v, UNKNOWN_TYPE))
        edges.add((v, u, UNKNOWN_TYPE))
        violating.append((u, v, UNKNOWN_TYPE))
    # Near-miss: planted path with final edge flipped inadmissible.
    bad_tail = "contradicts" if seq[-1] != "contradicts" else "invalidates"
    nearmiss = (tuple(list(planted[:-1]) + [(planted[-1][0],
                                             planted[-1][1], bad_tail)]),)
    graph = GeneratedGraph(nodes=tuple(nodes),
                           edges=tuple(sorted(edges)),
                           strata=params, seed=seed)
    truth = GroundTruth(planted=(planted,), hubs=hubs,
                        violating_edges=tuple(violating),
                        nearmiss=nearmiss, strata=params, seed=seed)
    return BenchmarkInstance(graph=graph, truth=truth)


def edge_seq(path: Sequence[Mapping[str, object]]
             ) -> tuple[tuple[str, str, str], ...]:
    """Canonical path identity for hit-checking (exact triple match)."""
    return tuple((str(e["src"]), str(e["dst"]), str(e["edge_type"]))
                 for e in path)


def recall_at_k(returned: Sequence[tuple[tuple[str, str, str], ...]],
                planted: Sequence[tuple[tuple[str, str, str], ...]]) -> float:
    """Fraction of planted bridges exactly matched. Empty planted →
    0.0 by definition (never NaN)."""
    if not planted:
        return 0.0
    got = set(returned)
    return sum(1 for p in planted if p in got) / len(planted)


def jaccard(a: tuple[tuple[str, str, str], ...],
            b: tuple[tuple[str, str, str], ...]) -> float:
    """Edge-set Jaccard (D2 sensitivity metric)."""
    sa, sb = set(a), set(b)
    if not sa and not sb:
        return 1.0
    return len(sa & sb) / len(sa | sb)


__all__ = [
    "BASE_TYPE",
    "UNKNOWN_TYPE",
    "BenchmarkInstance",
    "GeneratedGraph",
    "GroundTruth",
    "PlantingError",
    "StrataParams",
    "as_adjacency",
    "edge_seq",
    "generate",
    "jaccard",
    "recall_at_k",
]
