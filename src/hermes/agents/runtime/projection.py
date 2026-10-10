"""Read-side projections over the run trace — the B-5 slot (§4 B-5).

Borrowed behaviour, and the guard it carries
--------------------------------------------
B-5 permits borrowing "typed event/notification ordering with declared handler
dependencies", but only for **derived read-side projections**, and it requires a
**mechanical purity test**: the projection module must provably have no `conn`,
no `execute`, and no writer/journal imports. The source's bus is in-memory and
must never be re-implemented as a durable stream.

So this module is a set of pure functions over an iterable of `TraceEvent`:

* it imports exactly one thing from Hermes — `hermes.agents.runtime.types` — and
  nothing else (`collections.abc`, `dataclasses`, `types`, `typing` are stdlib);
* it never opens a file, never touches a connection, never writes anything, and
  holds no mutable state between calls (the one module-level mapping is a
  read-only declaration, and every result is recomputed from its input);
* ordering is *declared*: `HANDLER_DEPENDENCIES` names, per kind, the kinds a
  handler needs to have seen first, and `project_trace` orders that graph
  deterministically (arrival order breaks every tie), reporting what it could not
  satisfy instead of guessing.

Diagnostics, not exceptions
---------------------------
A projection is a *view*: an unknown kind, a cycle among declared dependencies,
or a dependency absent from this batch are all reported as data (`unknown`,
`cycles`, `unsatisfied`). The one thing that could not be tolerated — a hidden
write — is excluded by construction and by the suite's AST scan.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any

from hermes.agents.runtime.types import TRACE_KINDS, TraceEvent, digest_of

#: Declared handler dependencies: kind → the kinds whose handlers this kind's
#: handler must follow. Ordering is a declaration, never an incidental arrival
#: order (that is the whole point of the borrow). Kinds whose provenance is a
#: recovery pass rather than a live run declare none, because the batch may
#: legitimately contain them alone. Read-only: a projection declares, it never
#: mutates.
HANDLER_DEPENDENCIES: Mapping[str, tuple[str, ...]] = MappingProxyType({
    "RUN_STARTED": (),
    "RUN_RESUMED": ("RESUME_REQUESTED",),
    "TICK_STARTED": (),
    "MODEL_REQUESTED": ("TICK_STARTED",),
    "MODEL_REFUSED": ("MODEL_REQUESTED",),
    "PROPOSAL_DRAFTED": ("MODEL_REQUESTED",),
    "PROPOSAL_REFUSED": ("MODEL_REQUESTED",),
    "INTENT_EMITTED": ("PROPOSAL_DRAFTED",),
    "INTENT_ADMITTED": ("INTENT_EMITTED",),
    "INTENT_DUPLICATE": ("INTENT_EMITTED",),
    "INTENT_REFUSED": ("INTENT_EMITTED",),
    "TOOL_REQUESTED": ("TICK_STARTED",),
    "TOOL_OBSERVED": ("TOOL_REQUESTED",),
    "TOOL_FAILED": ("TOOL_REQUESTED",),
    "TOOL_SKIPPED": ("TOOL_REQUESTED",),
    "DELEGATION_PLANNED": ("TICK_STARTED",),
    "DELEGATION_REFUSED": ("DELEGATION_PLANNED",),
    "DELEGATION_COMPLETED": ("DELEGATION_PLANNED",),
    "DELEGATION_NOT_RESTARTED": (),
    "CHECKPOINT_WRITTEN": ("TICK_STARTED",),
    "RECOVERY_CLASSIFIED": (),
    "RESUME_REQUESTED": (),
    "RESUME_REJECTED": ("RESUME_REQUESTED",),
    "RESUME_NOOP": ("RESUME_REQUESTED",),
    "RUN_TERMINATED": (),
})


@dataclass(frozen=True, slots=True)
class ProjectedTrace:
    """The projection's whole output — data, recomputed, never persisted."""

    ordered: tuple[TraceEvent, ...]
    kind_order: tuple[str, ...]
    counts: Mapping[str, int]
    unsatisfied: tuple[str, ...]
    unknown: tuple[str, ...]
    cycles: tuple[str, ...]
    digest: str

    def sequence_is_monotonic(self) -> bool:
        sequences = [event.sequence for event in self.ordered]
        return sequences == sorted(sequences)

    def events_for(self, kind: str) -> tuple[TraceEvent, ...]:
        return tuple(event for event in self.ordered if event.kind == kind)


def order_events(events: Iterable[TraceEvent]
                 ) -> tuple[tuple[TraceEvent, ...], tuple[str, ...],
                            tuple[str, ...], tuple[str, ...]]:
    """Order events by declared handler dependency, arrival order as tie-break.

    Returns `(ordered, kind_order, unsatisfied, cycles)`. Pure, total and
    deterministic: the input is never mutated, nothing outside the arguments is
    read, and the same input always yields the same ordering.
    """
    items = tuple(events)
    arrival: dict[str, int] = {}
    for position, event in enumerate(items):
        arrival.setdefault(event.kind, position)
    kinds = sorted(arrival, key=lambda kind: arrival[kind])

    def declared(kind: str) -> tuple[str, ...]:
        return HANDLER_DEPENDENCIES.get(kind, ())

    def needed(kind: str) -> tuple[str, ...]:
        return tuple(dep for dep in declared(kind)
                     if dep in arrival and dep != kind)

    unsatisfied = tuple(
        kind for kind in kinds
        if any(dep == kind or dep not in arrival for dep in declared(kind)))

    resolved: list[str] = []
    pending = list(kinds)
    cycles: tuple[str, ...] = ()
    while pending:
        progressed = False
        for kind in list(pending):
            if all(dep in resolved for dep in needed(kind)):
                resolved.append(kind)
                pending.remove(kind)
                progressed = True
        if not progressed:
            cycles = tuple(pending)
            break

    ordered: list[TraceEvent] = []
    for kind in resolved:
        ordered.extend(event for event in items if event.kind == kind)
    for kind in cycles:
        ordered.extend(event for event in items if event.kind == kind)
    return tuple(ordered), tuple(resolved), unsatisfied, cycles


def counts_by_kind(events: Iterable[TraceEvent]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for event in events:
        counts[event.kind] = counts.get(event.kind, 0) + 1
    return counts


def trace_digest(events: Iterable[TraceEvent]) -> str:
    """A content digest of the trace — recomputed, never stored by this module."""
    return digest_of([{"sequence": event.sequence, "kind": event.kind,
                       "tick": event.tick, "run_id": event.run_id,
                       "lease_generation": event.lease_generation,
                       "at": event.at, "detail": dict(event.detail)}
                      for event in events])


def project_trace(events: Iterable[TraceEvent]) -> ProjectedTrace:
    """The whole projection in one pure call."""
    items = tuple(events)
    ordered, kind_order, unsatisfied, cycles = order_events(items)
    unknown = tuple(kind for kind in kind_order if kind not in TRACE_KINDS)
    return ProjectedTrace(
        ordered=ordered,
        kind_order=kind_order,
        counts=counts_by_kind(items),
        unsatisfied=unsatisfied,
        unknown=unknown,
        cycles=cycles,
        digest=trace_digest(items),
    )


def run_summary(events: Iterable[TraceEvent]) -> Mapping[str, Any]:
    """A compact, JSON-serialisable view of what a run's trace says."""
    items = tuple(events)
    counts = counts_by_kind(items)
    return {
        "events": len(items),
        "ticks": max((event.tick for event in items), default=0),
        "counts": counts,
        "proposals": counts.get("PROPOSAL_DRAFTED", 0),
        "admitted": counts.get("INTENT_ADMITTED", 0),
        "duplicates": counts.get("INTENT_DUPLICATE", 0),
        "refused": (counts.get("PROPOSAL_REFUSED", 0)
                    + counts.get("INTENT_REFUSED", 0)
                    + counts.get("MODEL_REFUSED", 0)
                    + counts.get("TOOL_FAILED", 0)
                    + counts.get("DELEGATION_REFUSED", 0)),
        "delegations": counts.get("DELEGATION_PLANNED", 0),
        "lease_generations": sorted({event.lease_generation for event in items}),
        "digest": trace_digest(items),
    }


def events_by_tick(events: Iterable[TraceEvent]) -> Mapping[int, tuple[TraceEvent, ...]]:
    grouped: dict[int, list[TraceEvent]] = {}
    for event in events:
        grouped.setdefault(event.tick, []).append(event)
    return {tick: tuple(grouped[tick]) for tick in sorted(grouped)}
