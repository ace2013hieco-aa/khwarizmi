"""Q-02 §7 — deterministic obligation-fact derivation (option C, evaluator v1.2).

Pure derivation of the six epistemic dimension facts from compiled program
rows + the project's artifact inventory. It lives OUTSIDE ``evaluation.py``
so the ActionEvaluation surface keeps its no-ladder-vocabulary purity guard
(test_evaluation AC-05); it imports the shared ``DimensionLevel`` vocabulary
from evaluation, so the ordering policy has exactly one source.

The count→level mapping is the ratified policy (versioned with the evaluator
triple): NONE when no obligation of that kind exists; LOW when obligations
exist but are all satisfied; MEDIUM for exactly one outstanding obligation;
HIGH for two or more. Dimensions with no stored source in the current schema
(contradiction_reduction, frontier_value, coverage) are always NONE — the
honest §18.4 degeneracy, documented, never a guess. An evidence requirement
is satisfied PER-REQUIREMENT (IDR-038 §3.1): via the stored satisfaction
links (``satisfactions``), a requirement is fulfilled iff every artifact
class in its ``required_artifacts`` has been linked to it. Discrimination
requirements are
outstanding obligations (their satisfaction is not recorded in the current
schema), so they always count as outstanding.

This module is pure: no SQL, no persistence imports, no write path, no
LLM input. Malformed program entries are skipped — a corrupt program never
becomes an ordering fact (fail-closed).
"""
from __future__ import annotations

from typing import Any, Mapping, Sequence

from hermes.research.evaluation import DimensionLevel


def _obligation_level(outstanding: int, total: int) -> DimensionLevel:
    """The ratified count→level mapping (part of the policy version)."""
    if total <= 0:
        return DimensionLevel.NONE
    if outstanding <= 0:
        return DimensionLevel.LOW
    if outstanding == 1:
        return DimensionLevel.MEDIUM
    return DimensionLevel.HIGH


def program_obligation_dimensions(
    programs: Sequence[Mapping[str, Any]],
    *,
    satisfactions: Mapping[str, Mapping[str, frozenset[str]]] | None = None,
) -> tuple[dict[str, DimensionLevel], tuple[str, ...]]:
    """Derive the six epistemic dimension facts from compiled program rows.

    ``programs`` are ``research_programs`` rows in the persistence layer's
    parsed
    shape (``hypotheses`` / ``evidence_requirements`` /
    ``discrimination_requirements`` lists, each a plain mapping).
    ``satisfactions`` maps ``{program_id: {requirement_ref: frozenset(
    artifact_types_fulfilling_it)}}`` — the per-requirement fulfillment facts
    from the stored satisfaction links (IDR-038 §3.1); a requirement with no
    entry is outstanding. Malformed entries are skipped. Counts are summed
    across programs (all obligations reachable from the task's program
    links). Returns
    ``(dimension→DimensionLevel, sorted basis_refs)`` where every non-NONE
    fact cites its ``research_program:<id>:...`` basis (Q-02 §9).
    """
    total_evidence = 0
    outstanding_evidence = 0
    total_rivals = 0
    outstanding_rivals = 0
    total_replication = 0
    outstanding_replication = 0
    basis: list[str] = []

    for program in programs:
        pid = program.get("program_id")
        evidence = program.get("evidence_requirements") or []
        for req in evidence:
            if not isinstance(req, Mapping):
                continue
            target = req.get("ladder_target")
            required = req.get("required_artifacts") or []
            if not isinstance(required, (list, tuple)) or not required:
                continue  # malformed obligation — skipped, never a fact
            per_req: Mapping[str, frozenset[str]] = (
                (satisfactions or {}).get(str(pid), {}))
            claim_ref = req.get("claim_ref")
            fulfilled = per_req.get(str(claim_ref), frozenset()) if claim_ref                 else frozenset()
            satisfied = all(a in fulfilled for a in required)
            total_evidence += 1
            if not satisfied:
                outstanding_evidence += 1
                if pid:
                    basis.append(
                        f"research_program:{pid}:evidence_requirement:"
                        f"{req.get('claim_ref')}")
            if target == "REPLICATED":
                total_replication += 1
                if not satisfied:
                    outstanding_replication += 1

        hypotheses = program.get("hypotheses") or []
        for hyp in hypotheses:
            if not isinstance(hyp, Mapping):
                continue
            if hyp.get("rival_of"):
                total_rivals += 1
                if hyp.get("rival_status") == "UNRESOLVED":
                    outstanding_rivals += 1
                    if pid and hyp.get("ref"):
                        basis.append(
                            f"research_program:{pid}:rival:{hyp.get('ref')}")

        discriminations = program.get("discrimination_requirements") or []
        for disc in discriminations:
            if not isinstance(disc, Mapping) or not disc.get("ref"):
                continue
            total_rivals += 1
            outstanding_rivals += 1  # satisfaction not recorded — outstanding
            if pid:
                basis.append(
                    f"research_program:{pid}:discrimination:{disc.get('ref')}")

    dims: dict[str, DimensionLevel] = {
        "evidence_gap_closure": _obligation_level(
            outstanding_evidence, total_evidence),
        "contradiction_reduction": DimensionLevel.NONE,   # no stored source
        "rival_discrimination": _obligation_level(
            outstanding_rivals, total_rivals),
        "replication_value": _obligation_level(
            outstanding_replication, total_replication),
        "frontier_value": DimensionLevel.NONE,            # no stored source
        "coverage": DimensionLevel.NONE,                  # no stored source
    }
    return dims, tuple(sorted(set(basis)))
