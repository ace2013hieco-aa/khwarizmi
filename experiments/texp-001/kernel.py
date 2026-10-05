"""TEXP-001 S3 — shared Metropolis proposal kernel (Case B, outside src/).

Fixed-temperature Metropolis chain over validator-admissible paths.
STIPULATED reference implementation (no production sampler exists — B1).
Pure except for explicitly injected seams; deterministic given seed;
stdlib-only (``__future__``, ``dataclasses``, ``hashlib``, ``math``,
``typing``). No model calls, no I/O, no clock, no writes.

Boundary: temperature is a FIXED per-run constant supplied by the caller;
choosing it across runs belongs to S4 arms. This module holds no
per-iteration temperature state.

Shared-code seam (C6): energy and validator arrive as injected callables
(S1 validator + S2 energy in production use of this track). The kernel
calls the validator ONLY through the injected callable's accept/reject
verdict — never its alphabet, table, or other internals. K-S2c holds by
construction: energy values stay local floats; nothing is written
anywhere.
"""

from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass
from typing import Callable, Mapping, Sequence

# An edge as the generator represents it (same shape S1 validates).
Edge = Mapping[str, object]
# Adjacency: node -> outgoing edge mappings (each carries at least
# "edge_type: str" plus whatever the generator stores; the kernel reads
# only edge_type and dst).
Graph = Mapping[str, Sequence[Edge]]

# Validator verdict shape: the kernel uses accepted/reason only.
ValidatorFn = Callable[[Sequence[Edge]], object]
EnergyFn = Callable[[Sequence[Edge], object], float]

_PROPOSE_RETRIES = 8


class BudgetOverrun(Exception):
    """Raised by BudgetCounter when an evaluation would exceed budget."""


@dataclass
class BudgetCounter:
    """Counts energy evaluations; raises on overrun. Every energy call
    goes through :meth:`evaluate` (rejected proposals included — D3);
    restarts spend one unit via :meth:`spend` (stipulated minimal
    accounting: D3 counts restarts in budget without fixing their price).
    """

    budget: int
    used: int = 0

    def evaluate(self, fn: EnergyFn, path: Sequence[Edge],
                 context: object) -> float:
        if self.used >= self.budget:
            raise BudgetOverrun(
                f"budget {self.budget} exhausted at {self.used} used")
        self.used += 1
        return fn(path, context)

    def spend(self, n: int = 1) -> None:
        if self.used + n > self.budget:
            raise BudgetOverrun(
                f"spend {n} would exceed budget {self.budget} "
                f"at {self.used} used")
        self.used += n


def make_rng_stream(graph_id: str, seed: int, stream: str = "proposal",
                    ) -> "object":
    """Independent RNG stream per (graph, seed, stream), derived by
    hashing (spec D5). Distinct streams never share state: each call
    builds a fresh ``random.Random`` from the digest — no module-level
    generator exists, so cross-stream sharing is constructionally
    impossible."""
    import random
    digest = hashlib.sha256(
        f"{graph_id}\x00{seed}\x00{stream}".encode("utf-8")).hexdigest()
    return random.Random(int(digest, 16))


def _dst_of(edge: Edge, node: str) -> str:
    dst = edge.get("dst", node)
    return dst if isinstance(dst, str) and dst else node


def initial_path(rng: object, graph: Graph, validator: ValidatorFn,
                 l_max: int) -> list[Edge]:
    """Fresh admissible single edge from a random node (bounded retries).
    Raises BudgetOverrun-neutral LookupError if none found (caller
    decides; no budget consumed — no energy evaluated)."""
    nodes = sorted(graph.keys())
    if not nodes:
        raise LookupError("empty graph: no start node")
    for _ in range(_PROPOSE_RETRIES * 4):
        node = nodes[rng.randrange(len(nodes))]  # type: ignore[union-attr]
        for edge in graph.get(node, ()):
            if not isinstance(edge, Mapping):
                continue
            cand = [edge]
            if len(cand) <= l_max and _accepted(validator, cand):
                return cand
    raise LookupError("no admissible single-edge start found")


def _accepted(validator: ValidatorFn, path: Sequence[Edge]) -> bool:
    return bool(getattr(validator(path), "accepted", False))


def propose(rng: object, current: Sequence[Edge], graph: Graph,
            validator: ValidatorFn, l_max: int) -> list[Edge] | None:
    """Single mutation: keep a random prefix, regrow a random-walk suffix
    truncated to ``l_max``. Returns None when no admissible regrowth is
    found within bounded retries (caller keeps current — no silent pass).
    Only validator accept/reject verdicts are consulted, never internals.
    """
    cur = list(current)
    for _ in range(_PROPOSE_RETRIES):
        cut = rng.randrange(len(cur) + 1)  # type: ignore[union-attr]
        prefix = cur[:cut]
        node = _dst_of(prefix[-1], "") if prefix else None
        if node is None:
            nodes = sorted(graph.keys())
            if not nodes:
                return None
            node = nodes[rng.randrange(len(nodes))]  # type: ignore[union-attr]
        grown = list(prefix)
        steps = 0
        while len(grown) < l_max and steps < l_max * 2:
            outs = [e for e in graph.get(node, ()) if isinstance(e, Mapping)]
            if not outs:
                break
            edge = outs[rng.randrange(len(outs))]  # type: ignore[union-attr]
            grown.append(edge)
            node = _dst_of(edge, node)
            steps += 1
        if grown and grown != cur and _accepted(validator, grown):
            return grown
    return None


@dataclass(frozen=True, slots=True)
class ChainResult:
    """Trajectory summary. Energies are local floats by construction
    (K-S2c): this record is in-memory only and carries no provenance
    beyond the run parameters."""

    best_path: tuple[Edge, ...]
    best_energy: float
    steps: int
    accepted: int
    metro_rejects: int
    validator_rejects: int
    restarts: int
    budget_used: int
    truncated: bool
    temperature: float


@dataclass
class ChainConfig:
    temperature: float
    budget: int
    l_max: int = 4
    restart_prob: float = 0.0
    max_steps: int = 10_000


def run_chain(rng: object, initial: Sequence[Edge], graph: Graph,
              validator: ValidatorFn, energy: EnergyFn, context: object,
              counter: BudgetCounter, config: ChainConfig) -> ChainResult:
    """Fixed-T Metropolis chain. Raises ValueError on non-positive
    temperature (fixed-T chains need T > 0; T = 0 greedy is out of
    scope for this reference). mid-run overrun sets `truncated`;
    initial-eval overrun propagates `BudgetOverrun` (the counter itself
    still raises — tested directly). Restarts reset to ``initial`` and
    spend one unit
    (stipulated restart policy)."""
    if not config.temperature > 0:
        raise ValueError(
            f"temperature must be > 0, got {config.temperature!r}")
    current = list(initial)
    cur_e = counter.evaluate(energy, current, context)
    best, best_e = tuple(current), cur_e
    accepted = metro_rejects = validator_rejects = restarts = 0
    truncated = False
    steps = 0
    while steps < config.max_steps:
        if counter.used >= counter.budget:
            truncated = True
            break
        steps += 1
        if config.restart_prob > 0 and rng.random() < config.restart_prob:  # type: ignore[union-attr]
            try:
                counter.spend(1)
            except BudgetOverrun:
                truncated = True
                break
            current = list(initial)
            try:
                cur_e = counter.evaluate(energy, current, context)
            except BudgetOverrun:
                truncated = True
                break
            restarts += 1
            continue
        cand = propose(rng, current, graph, validator, config.l_max)
        if cand is None:
            continue
        if not _accepted(validator, cand):
            validator_rejects += 1
            continue
        try:
            cand_e = counter.evaluate(energy, cand, context)
        except BudgetOverrun:
            truncated = True
            break
        if cand_e <= cur_e or rng.random() < math.exp(  # type: ignore[union-attr]
                -(cand_e - cur_e) / config.temperature):
            current, cur_e = cand, cand_e
            accepted += 1
            if cand_e < best_e:
                best, best_e = tuple(cand), cand_e
        else:
            metro_rejects += 1
    return ChainResult(
        best_path=best, best_energy=best_e, steps=steps, accepted=accepted,
        metro_rejects=metro_rejects, validator_rejects=validator_rejects,
        restarts=restarts, budget_used=counter.used, truncated=truncated,
        temperature=config.temperature)


__all__ = [
    "BudgetCounter",
    "BudgetOverrun",
    "ChainConfig",
    "ChainResult",
    "Graph",
    "Edge",
    "EnergyFn",
    "ValidatorFn",
    "initial_path",
    "make_rng_stream",
    "propose",
    "run_chain",
]
