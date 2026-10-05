"""Task graph (v4 §7) — persisted DAG, the authoritative operational plan.

The graph is a DAG stored in the ``tasks`` and ``task_dependencies`` tables.
The reconcile loop advances it (v4 §8). Key rules:

1. **Dependencies** — a node becomes READY when all deps are SUCCEEDED and
   none is INVALIDATED (v4 §7 rule 1).
2. **Loops are re-instantiation, not cycles** — a new research iteration
   creates a new subgraph while preserving the previous one (v4 §7 rule 3).
3. **INVALIDATED semantics** — invalidated results stay archived; a new
   node is created for the re-run (v4 §7 rule 4).

This module provides graph queries over the persisted state. The actual
persistence (INSERT, UPDATE) is in ``persistence/repositories.py``.
Domain objects never touch SQL (IDR-007, Phase 1 req §18).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

from hermes.core.task_status import TaskStatus


@dataclass(frozen=True, slots=True)
class ReadinessResult:
    """Result of a readiness check for a task node."""

    task_id: str
    ready: bool
    unfulfilled_deps: list[str] = field(default_factory=list)
    invalidated_deps: list[str] = field(default_factory=list)

    @property
    def blocked(self) -> bool:
        """True if any dependency is INVALIDATED (cannot become ready)."""
        return len(self.invalidated_deps) > 0


def is_ready(
    task_id: str,
    dependencies: list[str],
    dep_statuses: dict[str, str],
) -> ReadinessResult:
    """Determine readiness for a task given its dependencies' statuses.

    Args:
        task_id: The task to check.
        dependencies: List of task_ids this task depends on.
        dep_statuses: Map of {dep_task_id: status} for all dependencies.

    Returns:
        ReadinessResult with ``ready=True`` if all deps are SUCCEEDED.
        ``unfulfilled_deps`` lists deps not yet SUCCEEDED.
        ``invalidated_deps`` lists deps that are INVALIDATED (permanently blocked).
    """
    if not dependencies:
        return ReadinessResult(task_id=task_id, ready=True)

    unfulfilled: list[str] = []
    invalidated: list[str] = []

    for dep_id in dependencies:
        status = dep_statuses.get(dep_id, TaskStatus.PENDING.value)
        if status == TaskStatus.INVALIDATED.value:
            invalidated.append(dep_id)
        elif status != TaskStatus.SUCCEEDED.value:
            unfulfilled.append(dep_id)

    return ReadinessResult(
        task_id=task_id,
        ready=len(unfulfilled) == 0 and len(invalidated) == 0,
        unfulfilled_deps=unfulfilled,
        invalidated_deps=invalidated,
    )


def compute_subgraph_for_iteration(
    all_tasks: list[dict],
    iteration: int,
) -> list[dict]:
    """Filter tasks belonging to a specific research iteration.

    v4 §7 rule 3: each new iteration creates new nodes; old nodes are
    preserved. This function returns only the tasks for the given iteration,
    enabling the reconcile loop to operate on the current iteration's subgraph.
    """
    return [t for t in all_tasks if t.get("iteration") == iteration]


def detect_cycle(
    task_id: str,
    dependencies: dict[str, list[str]],
) -> list[str] | None:
    """F-11: Detect if adding edges from task_id creates a cycle.

    Uses DFS to check if task_id is reachable from any of its dependencies
    (which would mean adding task_id → dep creates a cycle).

    Args:
        task_id: The task that would be added with dependencies.
        dependencies: Map of {task_id: [dep_ids]} for all existing tasks.

    Returns:
        None if no cycle, or a list of task_ids forming the cycle path.
    """
    visited: set[str] = set()
    path: list[str] = []

    def _dfs(current: str) -> list[str] | None:
        if current == task_id:
            return path + [current]
        if current in visited:
            return None
        visited.add(current)
        path.append(current)
        for dep in dependencies.get(current, []):
            result = _dfs(dep)
            if result is not None:
                return result
        path.pop()
        return None

    # Check each dependency of task_id
    for dep in dependencies.get(task_id, []):
        result = _dfs(dep)
        if result is not None:
            return result
    return None


# ── Q-04: forward failure-propagation reachability (derived, read-only) ──
#
# Design gate: hermes_q04_failure_propagation_design_gate.md §3. The
# controller's eligibility check is LOCAL (direct deps SUCCEEDED); nothing
# answers "if A fails/retires/gets patched, what downstream is affected" —
# the transitive forward closure. These pure queries add exactly that, over
# the SAME ratified edge set (task_dependencies, loaded by the caller) and
# the SAME blocking predicate the controller uses — the graph is the
# transitive VIEW of the eligibility rule, never a second authority, never
# a writer, never a scheduler input. Pure: no SQL, no clock, no LLM input
# (IDR-007 — domain code never touches SQL).

GRAPH_QUERY_VERSION = "1"  # bound into every result hash (§3.3)


@dataclass(frozen=True, slots=True)
class FailureConeEntry:
    """One downstream task blocked by a seed failure (Q-04 §3.2)."""

    task_id: str
    blocking_ancestor: str   # the FIRST non-SUCCEEDED ancestor from the seed
    blocking_status: str     # that ancestor's status
    classification_label: str | None = None  # Q-05 label of the ancestor


def failure_cone(
    seed_task_ids: Sequence[str],
    dependents: Mapping[str, Sequence[str]],
    statuses: Mapping[str, str],
    classification_labels: Mapping[str, str] | None = None,
) -> tuple[FailureConeEntry, ...]:
    """Transitive dependents blocked by a seed task that is not SUCCEEDED.

    A dependent is in the cone iff it has a path from a seed whose source
    node is not SUCCEEDED (the controller's own eligibility predicate,
    transitively). Each entry is labeled with the FIRST non-SUCCEEDED
    ancestor on the path (the root cause) and that ancestor's status, plus
    its Q-05 classification label when recorded. Deterministic: sorted
    seeds, sorted dependents, first-visit-wins, output sorted by task_id.
    Cycle-defensive: a hand-inserted 2-cycle terminates (visited set).
    """
    labels = classification_labels or {}
    seeds = sorted(seed_task_ids)
    seen: set[str] = set(seeds)  # seeds are the cause, never a dependent
    out: dict[str, FailureConeEntry] = {}
    for seed in seeds:
        seed_status = statuses.get(seed, TaskStatus.PENDING.value)
        if seed_status == TaskStatus.SUCCEEDED.value:
            continue  # a SUCCEEDED seed blocks nothing
        # Frontier of (dependent, first-blocking-ancestor, its status).
        stack: list[tuple[str, str, str]] = [
            (dep, seed, seed_status)
            for dep in sorted(dependents.get(seed, ()))
        ]
        while stack:
            task_id, blocker, blocker_status = stack.pop()
            if task_id in seen:
                continue
            seen.add(task_id)
            out[task_id] = FailureConeEntry(
                task_id=task_id,
                blocking_ancestor=blocker,
                blocking_status=blocker_status,
                classification_label=labels.get(blocker),
            )
            # F9: propagate only through non-SUCCEEDED nodes — a SUCCEEDED
            # intermediate breaks the blocking chain (the predicate requires
            # EVERY edge source on the path to be not SUCCEEDED; a dependent
            # whose direct dep succeeded runs regardless of the seed).
            if task_id in out and statuses.get(
                    task_id, TaskStatus.PENDING.value) == TaskStatus.SUCCEEDED.value:
                continue  # already visited AND succeeded — chain broken
            for dep in sorted(dependents.get(task_id, ())):
                if dep not in seen:
                    stack.append((dep, blocker, blocker_status))
    return tuple(out[k] for k in sorted(out))


def blocked_roots(
    dependents: Mapping[str, Sequence[str]],
    statuses: Mapping[str, str],
) -> tuple[str, ...]:
    """Tasks whose dependency closure contains a TERMINAL FAILED ancestor —
    permanently blocked until the failure is resolved by IDR-029 or a new
    iteration (distinct from transiently blocked: a RETRYING ancestor is
    still on the recovery ladder). The FAILED seeds themselves are not
    blocked roots (they failed; they are the cause). Deterministic
    (sorted, first-visit-wins), cycle-defensive.
    """
    failed = sorted(
        t for t, s in statuses.items() if s == TaskStatus.FAILED.value)
    permanently_blocked: set[str] = set()
    for f in failed:
        stack = sorted(dependents.get(f, ()))
        while stack:
            task_id = stack.pop()
            if task_id in permanently_blocked:
                continue
            if statuses.get(task_id, TaskStatus.PENDING.value) == (
                    TaskStatus.SUCCEEDED.value):
                continue  # F9: succeeded — not blocked, and the chain stops
            permanently_blocked.add(task_id)
            stack.extend(sorted(dependents.get(task_id, ())))
    return tuple(sorted(
        t for t in permanently_blocked
        if statuses.get(t, TaskStatus.PENDING.value) != TaskStatus.SUCCEEDED.value))


def change_blast_radius(
    seed_task_ids: Sequence[str],
    dependents: Mapping[str, Sequence[str]],
) -> tuple[str, ...]:
    """The full transitive dependent closure of the seed set — the advisory
    "what would this affect" surface, REGARDLESS of current status (a patch
    or re-run affects downstream even when the seed currently SUCCEEDED).
    Deterministic (sorted, visited set), cycle-defensive.
    """
    seeds = sorted(seed_task_ids)
    seen: set[str] = set(seeds)  # seeds are the change origin, not affected
    affected: set[str] = set()
    for seed in seeds:
        stack = sorted(dependents.get(seed, ()))
        while stack:
            task_id = stack.pop()
            if task_id in seen:
                continue
            seen.add(task_id)
            affected.add(task_id)
            stack.extend(sorted(dependents.get(task_id, ())))
    return tuple(sorted(affected))


@dataclass(frozen=True, slots=True)
class ArtifactBlastEntry:
    """A downstream artifact reached from a source-artifact seed via a
    ``provenance_edges`` hop — labeled with the root seed that first reached
    it (the failure_cone labeling: FIRST ancestor, not the immediate hop)
    and the edge type of that first visit."""

    artifact_id: str
    reached_via: str
    edge_type: str


def artifact_blast_radius(
    seed_artifact_ids: Sequence[str],
    downstream: Mapping[str, Sequence[tuple[str, str]]],
) -> tuple[ArtifactBlastEntry, ...]:
    """Transitive downstream closure over ``provenance_edges`` (Q-04 §5
    extension): every artifact that cites, derives from, uses as input,
    supersedes, or is justified by a seed artifact — transitively — the
    artifacts needing re-review when a source artifact is retracted or
    superseded. The artifact-layer analog of ``change_blast_radius``:
    reachability REGARDLESS of any downstream status (the provenance
    lineage is the fact; review need does not depend on a status).

    ``downstream`` maps an upstream artifact id to its outgoing edges as
    ``(artifact_id, edge_type)`` pairs — the ``provenance_edges`` row shape
    (the artifact cites/derives from the upstream). Deterministic: sorted
    seeds, sorted edge lists, first-visit-wins, output sorted by
    artifact_id. Cycle-defensive: a hand-inserted 2-cycle terminates
    (visited set). Seeds are the origin, never a result.
    """
    seeds = sorted(seed_artifact_ids)
    seen: set[str] = set(seeds)
    out: dict[str, ArtifactBlastEntry] = {}
    for seed in seeds:
        stack = sorted(
            downstream.get(seed, ()), key=lambda pair: (pair[0], pair[1]))
        while stack:
            artifact_id, edge_type = stack.pop()
            if artifact_id in seen:
                continue
            seen.add(artifact_id)
            out[artifact_id] = ArtifactBlastEntry(
                artifact_id=artifact_id,
                reached_via=seed,
                edge_type=edge_type,
            )
            stack.extend(sorted(
                downstream.get(artifact_id, ()),
                key=lambda pair: (pair[0], pair[1])))
    return tuple(out[k] for k in sorted(out))


@dataclass(frozen=True, slots=True)
class ReviewCandidate:
    """A downstream artifact that BOTH (a) is in the blast radius of a
    retracted/superseded source and (b) carries at least one OUTSTANDING
    Q-05 classification — the concrete re-review candidate. The
    classification refs are the D3 ``failure_classification:<hash>`` refs;
    ``requires_human_confirmation`` is True when any cited classification
    requires human confirmation."""

    artifact_id: str
    reached_via: str
    edge_type: str
    classification_refs: tuple[str, ...]
    failure_classes: tuple[str, ...]
    requires_human_confirmation: bool


def re_review_candidates(
    blast: Sequence[ArtifactBlastEntry],
    classifications_by_artifact: Mapping[str, Sequence[Mapping[str, Any]]],
) -> tuple[ReviewCandidate, ...]:
    """The intersection of the artifact blast radius with OUTSTANDING Q-05
    classifications (D8-valid, unflagged digest items): ``classifications_by_artifact``
    maps an evidence artifact id to the digest items that cite it. A
    downstream artifact is a candidate iff it has at least one valid
    classification. Deterministic (sorted, refs/classes sorted), pure —
    never a writer, never a retractor: it only names what needs re-review.
    """
    out: list[ReviewCandidate] = []
    for e in sorted(blast, key=lambda b: b.artifact_id):
        items = [i for i in classifications_by_artifact.get(e.artifact_id, ())
                 if isinstance(i, Mapping)]
        refs = tuple(sorted(
            str(i.get("failure_class_ref") or "")
            for i in items if i.get("failure_class_ref")))
        if not refs:
            continue  # no outstanding classification — not a candidate
        classes = tuple(sorted(
            str(i.get("failure_class") or "")
            for i in items if i.get("failure_class")))
        out.append(ReviewCandidate(
            artifact_id=e.artifact_id,
            reached_via=e.reached_via,
            edge_type=e.edge_type,
            classification_refs=refs,
            failure_classes=classes,
            requires_human_confirmation=any(
                bool(i.get("requires_human_confirmation")) for i in items),
        ))
    return tuple(out)


def graph_result_hash(kind: str, payload: Any) -> str:
    """Content hash binding GRAPH_QUERY_VERSION to a result payload (§3.3):
    same state + same query version ⇒ same identity. Never persisted —
    recomputed per query, so there is no stored-version drift."""
    body = {
        "version": GRAPH_QUERY_VERSION,
        "kind": kind,
        "payload": payload,
    }
    import hashlib
    import json as _json
    return hashlib.sha256(_json.dumps(
        body, sort_keys=True, separators=(",", ":"),
        default=str).encode("utf-8")).hexdigest()
