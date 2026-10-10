"""Repositories (v4 §16) — typed read/write over stores; no business logic.

Repository boundary (Phase 1 req §18):
    Domain → Repository interface → SQLite repository → SQLite

Domain objects never touch SQL. The CLI and other callers use the same
repository APIs. Transition + event are atomic within a single transaction
(IDR-013).

F-01: All transition methods read and validate state INSIDE the
``BEGIN IMMEDIATE`` transaction — never before it. This prevents the
read-before-lock race where two workers read the same stale state.

F-04: All events are validated at the persistence boundary (S6) before
INSERT — payload size cap, event-type check, secret rejection.

F-08: Mode transitions are rejected when the project's lifecycle is in a
terminal state (v4 §6.2: "Modes apply only to non-terminal lifecycle states").

F-09: ``advance_iteration`` emits an ``IterationAdvanced`` event atomically
with the mutation (v4 §8.1: every mutation is command→validate→apply→event).

F-10: ``transition_status`` rejects READY→RUNNING when any dependency is
INVALIDATED (v4 §7 rule 1: "a node becomes READY when all deps are SUCCEEDED
and none is INVALIDATED").
"""
from __future__ import annotations

import json
import sqlite3
import uuid
from typing import Any, Sequence

from hermes.core import Clock, utc_now
from hermes.core.lifecycle import (
    LifecycleState,
    TransitionError,
    validate_transition,
)
from hermes.core.modes import (
    OperationalMode,
    validate_mode_transition,
)
from hermes.core.node import NodeContract
from hermes.core.task_status import (
    TaskStatus,
    TaskTransitionError,
    validate_task_transition,
)
from hermes.persistence.event_validation import validate_event
from hermes.persistence.source_outcomes import _source_artifact_resolves
from hermes.research.claims import (
    CLAIM_SCHEMA_VERSION,
    DEREFERENCE_DIMENSIONS,
    REF_SEP,
    ContextResolver,
    ExtractionResult,
    ExtractionVerdict,
    assumption_id_of,
    claim_id_of,
)
from hermes.research.extraction import EXTRACT_TEMPLATE
from hermes.research.programs import CompilationResult, CompilationStatus
from hermes.research.regimes import (
    RegimeResolutionError,
    parse_regime_ref,
    resolve_regime,
)
from hermes.research.thesis import EmptyResultResolver

# ── helpers ──

# Write-path dereference vocabulary for ``_dereference_artifact_ref``
# (IDR-026 / V6-P7-F02). CLOSED by audit (F1 generalization): every
# artifact type is explicitly decided — resolved against a real carrier,
# documented as a DEFERRED carrier (form-checked only, no store yet), or
# refused. A type with no explicit decision never passes silently.
#
# Deferred carriers are task-output context refs (the extraction batch
# source): legitimately citable as claim source_ref / supporting refs, but
# their store does not exist yet. When a store lands, it becomes a real
# resolver here — never a silent form-checked pass.
DEFERRED_ARTIFACT_CARRIERS = frozenset({"task_evidence", "task_output"})

def _json_dumps(value: Any) -> str:
    if value is None:
        return "null"
    return json.dumps(value, sort_keys=True, ensure_ascii=False)


def _json_loads(value: str | None) -> Any:
    if value is None or value == "":
        return None
    return json.loads(value)


def _append_event_to_db(
    conn: sqlite3.Connection,
    clock: Clock,
    event_type: str,
    project_id: str | None = None,
    task_id: str | None = None,
    from_state: str | None = None,
    to_state: str | None = None,
    correlation_id: str = "",
    caused_by: str | None = None,
    reason: str | None = None,
    artifact_ids: list[str] | None = None,
    payload: dict[str, Any] | None = None,
) -> None:
    """Insert an event row. Called within an existing transaction.

    ADD-01: Single implementation shared by ProjectRepository and
    TaskRepository. F-04 validates the event at the persistence boundary
    (S6) before INSERT — payload size cap, event-type check, secret
    rejection.
    """
    validate_event(event_type, payload)

    ts = clock()
    conn.execute(
        """INSERT INTO events
           (event_type, project_id, task_id, from_state, to_state,
            correlation_id, caused_by, reason, artifact_ids_json,
            payload_json, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (event_type, project_id, task_id, from_state, to_state,
         correlation_id, caused_by, reason,
         _json_dumps(artifact_ids or []), _json_dumps(payload or {}), ts),
    )


# ── errors ──

class NotFoundError(Exception):
    """Raised when a required entity is not found in the database."""


class DependencyError(Exception):
    """Raised when a task cannot transition due to dependency state (F-10)."""


class TerminalLifecycleError(Exception):
    """Raised when a mode transition is attempted on a terminal project (F-08)."""


# ── Project Repository ──

class ProjectRepository:
    """Read/write projects with atomic lifecycle + mode transitions."""

    def __init__(self, conn: sqlite3.Connection, clock: Clock | None = None):
        self._conn = conn
        self._clock = clock or utc_now

    def create(self, project_id: str, name: str) -> dict:
        """Create a new project in the CREATED lifecycle state."""
        ts = self._clock()
        self._conn.execute("BEGIN")
        try:
            self._conn.execute(
                """INSERT INTO projects (project_id, name, lifecycle_state,
                   operational_mode, iteration, created_at, updated_at)
                   VALUES (?, ?, 'CREATED', 'ACTIVE', 1, ?, ?)""",
                (project_id, name, ts, ts),
            )
            self._append_event(
                event_type="ResearchCreated",
                project_id=project_id,
                to_state="CREATED",
                correlation_id=str(uuid.uuid4()),
                caused_by="system",
            )
            self._conn.execute("COMMIT")
        except Exception:
            self._conn.execute("ROLLBACK")
            raise
        return self.get(project_id)

    def get(self, project_id: str) -> dict:
        row = self._conn.execute(
            "SELECT * FROM projects WHERE project_id = ?", (project_id,)
        ).fetchone()
        if row is None:
            raise NotFoundError(f"Project not found: {project_id}")
        return dict(row)

    def get_lifecycle(self, project_id: str) -> LifecycleState:
        row = self._conn.execute(
            "SELECT lifecycle_state FROM projects WHERE project_id = ?",
            (project_id,),
        ).fetchone()
        if row is None:
            raise NotFoundError(f"Project not found: {project_id}")
        return LifecycleState(row["lifecycle_state"])

    def get_mode(self, project_id: str) -> OperationalMode:
        row = self._conn.execute(
            "SELECT operational_mode FROM projects WHERE project_id = ?",
            (project_id,),
        ).fetchone()
        if row is None:
            raise NotFoundError(f"Project not found: {project_id}")
        return OperationalMode(row["operational_mode"])

    def transition_lifecycle(
        self,
        project_id: str,
        to_state: LifecycleState,
        caused_by: str = "controller",
        reason: str = "",
        artifact_ids: list[str] | None = None,
    ) -> dict:
        """Atomically transition lifecycle state + append event (IDR-013).

        F-01: The state read and validation happen INSIDE BEGIN IMMEDIATE
        to prevent the read-before-lock race. The event's from_state is the
        state actually observed while holding the write lock.

        Raises ``TransitionError`` if the transition is illegal.
        """
        ts = self._clock()
        correlation_id = str(uuid.uuid4())
        self._conn.execute("BEGIN IMMEDIATE")
        try:
            # F-01: Read current state WHILE holding the write lock
            from_state = self.get_lifecycle(project_id)
            # F-01: Validate WHILE holding the write lock
            validate_transition(from_state, to_state)

            # HR-08: the completion invariant. Operational termination is
            # not epistemic completion — reaching COMPLETED requires every
            # mandatory research obligation of the current compiled program
            # to be validly satisfied (verdict-covered satisfaction links,
            # mandatory gate audit events, no refuted hypothesis). The
            # structural table check above is necessary but NOT sufficient;
            # this guard is the single choke point so no current or future
            # driver can reach COMPLETED without the invariant holding.
            # Fail-closed: any denial refuses the transition.
            if to_state == LifecycleState.COMPLETED:
                from hermes.research.completion import can_complete_research
                eligibility = can_complete_research(self._conn, project_id)
                if not eligibility.eligible:
                    codes = "; ".join(
                        f"{d.code}:{d.subject}" for d in eligibility.denials)
                    raise TransitionError(
                        from_state, to_state,
                        reason=f"HR-08 completion invariant not met — {codes}")

            self._conn.execute(
                "UPDATE projects SET lifecycle_state = ?, updated_at = ? WHERE project_id = ?",
                (to_state.value, ts, project_id),
            )
            self._append_event(
                event_type="LifecycleTransition",
                project_id=project_id,
                from_state=from_state.value,
                to_state=to_state.value,
                correlation_id=correlation_id,
                caused_by=caused_by,
                reason=reason,
                artifact_ids=artifact_ids or [],
            )
            self._conn.execute("COMMIT")
        except Exception:
            self._conn.execute("ROLLBACK")
            raise
        return self.get(project_id)

    def transition_mode(
        self,
        project_id: str,
        to_mode: OperationalMode,
        caused_by: str = "operator",
        reason: str = "",
    ) -> dict:
        """Atomically transition operational mode + append event.

        F-01: Read + validate INSIDE BEGIN IMMEDIATE.
        F-08: Reject mode transitions when lifecycle is terminal (v4 §6.2).
        """
        ts = self._clock()
        correlation_id = str(uuid.uuid4())
        # Map mode to event type
        event_type = {
            OperationalMode.PAUSED: "ProjectPaused",
            OperationalMode.ACTIVE: "ProjectResumed",
            OperationalMode.AWAITING_HUMAN: "ModeChanged",
        }.get(to_mode, "ModeChanged")

        self._conn.execute("BEGIN IMMEDIATE")
        try:
            # F-01: Read current mode and lifecycle WHILE holding the lock
            from_mode = self.get_mode(project_id)
            validate_mode_transition(from_mode, to_mode)

            # F-08: Modes apply only to non-terminal lifecycle states
            current_lifecycle = self.get_lifecycle(project_id)
            if current_lifecycle in LifecycleState.terminal_states():
                raise TerminalLifecycleError(
                    f"Cannot transition mode on project in terminal lifecycle state "
                    f"{current_lifecycle.value} (v4 §6.2: modes apply only to non-terminal)"
                )

            self._conn.execute(
                "UPDATE projects SET operational_mode = ?, updated_at = ? WHERE project_id = ?",
                (to_mode.value, ts, project_id),
            )
            self._append_event(
                event_type=event_type,
                project_id=project_id,
                from_state=from_mode.value,
                to_state=to_mode.value,
                correlation_id=correlation_id,
                caused_by=caused_by,
                reason=reason,
            )
            self._conn.execute("COMMIT")
        except Exception:
            self._conn.execute("ROLLBACK")
            raise
        return self.get(project_id)

    def advance_iteration(self, project_id: str) -> int:
        """Increment the project's research iteration (v4 §7 rule 3).

        F-09: Emits an ``IterationAdvanced`` event atomically with the mutation
        (v4 §8.1: every mutation is command→validate→apply→event).
        """
        ts = self._clock()
        correlation_id = str(uuid.uuid4())
        self._conn.execute("BEGIN IMMEDIATE")
        try:
            # Read current iteration inside the lock
            row = self._conn.execute(
                "SELECT iteration FROM projects WHERE project_id = ?", (project_id,)
            ).fetchone()
            if row is None:
                raise NotFoundError(f"Project not found: {project_id}")
            old_iteration = row["iteration"]

            self._conn.execute(
                "UPDATE projects SET iteration = iteration + 1, updated_at = ? WHERE project_id = ?",
                (ts, project_id),
            )
            # F-09: Emit iteration event atomically
            self._append_event(
                event_type="IterationAdvanced",
                project_id=project_id,
                payload={"old_iteration": old_iteration, "new_iteration": old_iteration + 1},
                correlation_id=correlation_id,
                caused_by="controller",
                reason="research iteration advance",
            )
            self._conn.execute("COMMIT")
        except Exception:
            self._conn.execute("ROLLBACK")
            raise
        row = self._conn.execute(
            "SELECT iteration FROM projects WHERE project_id = ?", (project_id,)
        ).fetchone()
        return row["iteration"] if row else 0

    def list_all(self) -> list[dict]:
        rows = self._conn.execute(
            "SELECT * FROM projects ORDER BY created_at"
        ).fetchall()
        return [dict(r) for r in rows]

    def _append_event(self, event_type, project_id=None, task_id=None,
                      from_state=None, to_state=None, correlation_id="",
                      caused_by="", reason="", artifact_ids=None, payload=None):
        """Insert an event row. Called within an existing transaction.

        ADD-01: Delegates to the shared module-level ``_append_event_to_db``.
        F-04: Validates event at the persistence boundary (S6) before INSERT.
        """
        _append_event_to_db(
            self._conn, self._clock, event_type, project_id, task_id,
            from_state, to_state, correlation_id, caused_by, reason,
            artifact_ids, payload,
        )


# ── Task Repository ──

class TaskRepository:
    """Read/write task nodes with atomic status transitions."""

    def __init__(self, conn: sqlite3.Connection, clock: Clock | None = None):
        self._conn = conn
        self._clock = clock or utc_now

    def create(self, node: NodeContract) -> dict:
        """Insert a new task node. Fails on duplicate idempotency_key+attempt.

        F-11: Cycle detection — rejects dependencies that would create a cycle.
        """
        ts = self._clock()

        # F-11: Check for cycles before inserting
        if node.dependencies:
            self._check_no_cycle(node.task_id, node.dependencies)

        self._conn.execute("BEGIN")
        try:
            self._conn.execute(
                """INSERT INTO tasks
                   (task_id, project_id, task_type, profile, idempotency_key,
                    attempt, status, iteration, parent_task_id,
                    spec_json, inputs_json, outputs_json, provenance_json,
                    cost_class, concurrency_group, max_retries,
                    created_at, started_at, completed_at, last_heartbeat)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    node.task_id, node.project_id, node.task_type, node.profile,
                    node.idempotency_key, node.attempt, node.status,
                    node.iteration, node.parent_task_id,
                    _json_dumps(node.spec),
                    _json_dumps(node.inputs) if node.inputs else None,
                    _json_dumps(node.outputs) if node.outputs else None,
                    _json_dumps(node.provenance) if node.provenance else None,
                    node.cost_class, node.concurrency_group, node.max_retries,
                    ts, node.started_at, node.completed_at, node.last_heartbeat,
                ),
            )
            # Insert dependency edges
            for dep_id in node.dependencies:
                self._conn.execute(
                    """INSERT INTO task_dependencies (task_id, depends_on_task_id, created_at)
                       VALUES (?, ?, ?)""",
                    (node.task_id, dep_id, ts),
                )
            # Event
            self._append_event(
                event_type="TaskCreated",
                project_id=node.project_id,
                task_id=node.task_id,
                to_state=node.status,
                correlation_id=str(uuid.uuid4()),
                caused_by="controller",
            )
            self._conn.execute("COMMIT")
        except Exception:
            self._conn.execute("ROLLBACK")
            raise
        return self.get(node.task_id)

    def _check_no_cycle(self, task_id: str, dependencies: list[str]) -> None:
        """F-11: Detect cycles in the task graph before inserting.

        ADD-02: Delegates to ``graph.detect_cycle`` instead of maintaining
        a separate DFS. Loads the existing dependency map from the DB,
        adds the proposed edges for ``task_id``, and calls the pure
        ``detect_cycle`` function.

        Raises ``DependencyError`` with the same messages the original
        implementation used (preserving the "Self-cycle" message that
        ``test_phase1_acceptance`` asserts on).
        """
        # Self-cycle fast-path (preserves "Self-cycle" message)
        if task_id in dependencies:
            raise DependencyError(
                f"Self-cycle detected: task {task_id} cannot depend on itself"
            )

        # Build the full dependency map from the DB
        rows = self._conn.execute(
            "SELECT task_id, depends_on_task_id FROM task_dependencies"
        ).fetchall()
        dep_map: dict[str, list[str]] = {}
        for r in rows:
            dep_map.setdefault(r["task_id"], []).append(r["depends_on_task_id"])

        # Add the proposed edges for the new task
        dep_map[task_id] = list(dependencies)

        # Delegate to the pure function
        from hermes.core.graph import detect_cycle
        cycle = detect_cycle(task_id, dep_map)
        if cycle is not None:
            raise DependencyError(
                f"Cycle detected: {task_id} → {' → '.join(cycle)} → {task_id}"
            )

    def get(self, task_id: str) -> dict:
        row = self._conn.execute(
            "SELECT * FROM tasks WHERE task_id = ?", (task_id,)
        ).fetchone()
        if row is None:
            raise NotFoundError(f"Task not found: {task_id}")
        d = dict(row)
        d["spec"] = _json_loads(d.pop("spec_json"))
        d["inputs"] = _json_loads(d.pop("inputs_json")) or []
        d["outputs"] = _json_loads(d.pop("outputs_json")) or []
        d["provenance"] = _json_loads(d.pop("provenance_json")) or []
        d["dependencies"] = self.get_dependencies(task_id)
        return d

    def get_dependencies(self, task_id: str) -> list[str]:
        rows = self._conn.execute(
            "SELECT depends_on_task_id FROM task_dependencies WHERE task_id = ?",
            (task_id,),
        ).fetchall()
        return [r["depends_on_task_id"] for r in rows]

    def _get_dependency_statuses(self, task_id: str) -> dict[str, str]:
        """Get the status of all dependencies for a task."""
        deps = self.get_dependencies(task_id)
        if not deps:
            return {}
        statuses = {}
        for dep_id in deps:
            row = self._conn.execute(
                "SELECT status FROM tasks WHERE task_id = ?", (dep_id,)
            ).fetchone()
            statuses[dep_id] = row["status"] if row else "PENDING"
        return statuses

    def get_status(self, task_id: str) -> TaskStatus:
        row = self._conn.execute(
            "SELECT status FROM tasks WHERE task_id = ?", (task_id,)
        ).fetchone()
        if row is None:
            raise NotFoundError(f"Task not found: {task_id}")
        return TaskStatus(row["status"])

    def transition_status(
        self,
        task_id: str,
        to_status: TaskStatus,
        caused_by: str = "controller",
        reason: str = "",
    ) -> dict:
        """Atomically transition task status + append event (IDR-013).

        F-01: Read + validate INSIDE BEGIN IMMEDIATE.
        F-10: READY→RUNNING is rejected if any dependency is INVALIDATED.
        """
        ts = self._clock()
        correlation_id = str(uuid.uuid4())

        self._conn.execute("BEGIN IMMEDIATE")
        try:
            # F-01: Read state WHILE holding the write lock
            from_status = self.get_status(task_id)
            validate_task_transition(from_status, to_status)

            row = self._conn.execute(
                "SELECT project_id FROM tasks WHERE task_id = ?", (task_id,)
            ).fetchone()
            if row is None:
                raise NotFoundError(f"Task not found: {task_id}")
            project_id = row["project_id"]

            # F-10: Reject READY→RUNNING when any dependency is INVALIDATED
            # or FAILED (v4 §7 rule 1: "all deps SUCCEEDED and none INVALIDATED")
            if to_status == TaskStatus.RUNNING:
                dep_statuses = self._get_dependency_statuses(task_id)
                invalidated = [
                    dep_id for dep_id, st in dep_statuses.items()
                    if st == TaskStatus.INVALIDATED.value
                ]
                if invalidated:
                    raise DependencyError(
                        f"Cannot transition task {task_id} to RUNNING: "
                        f"dependency {invalidated[0]} is INVALIDATED (v4 §7 rule 1)"
                    )
                # F-10: Also reject if any dependency is not SUCCEEDED
                not_succeeded = [
                    dep_id for dep_id, st in dep_statuses.items()
                    if st != TaskStatus.SUCCEEDED.value
                ]
                if not_succeeded:
                    raise DependencyError(
                        f"Cannot transition task {task_id} to RUNNING: "
                        f"dependency {not_succeeded[0]} is not SUCCEEDED "
                        f"(status: {dep_statuses[not_succeeded[0]]}) (v4 §7 rule 1)"
                    )

            self._conn.execute(
                "UPDATE tasks SET status = ? WHERE task_id = ?",
                (to_status.value, task_id),
            )
            # IDR-029 Decision 4: a requeue (RETRYING → RUNNING) is a NEW
            # attempt — increment the retry-policy counter atomically with
            # the transition (PA1 R6 pattern; A2-03 one-shot is keyed on
            # producing_task_id, never on attempt, so idempotency survives).
            if (from_status is TaskStatus.RETRYING
                    and to_status is TaskStatus.RUNNING):
                self._conn.execute(
                    "UPDATE tasks SET attempt = attempt + 1 WHERE task_id = ?",
                    (task_id,),
                )
            # Update timestamps
            if to_status == TaskStatus.RUNNING:
                self._conn.execute(
                    "UPDATE tasks SET started_at = ? WHERE task_id = ? AND started_at IS NULL",
                    (ts, task_id),
                )
            elif to_status in {TaskStatus.SUCCEEDED, TaskStatus.FAILED,
                               TaskStatus.CANCELLED, TaskStatus.SKIPPED,
                               TaskStatus.INVALIDATED}:
                self._conn.execute(
                    "UPDATE tasks SET completed_at = ? WHERE task_id = ?",
                    (ts, task_id),
                )
            self._append_event(
                event_type="TaskStatusChanged",
                project_id=project_id,
                task_id=task_id,
                from_state=from_status.value,
                to_state=to_status.value,
                correlation_id=correlation_id,
                caused_by=caused_by,
                reason=reason,
            )
            self._conn.execute("COMMIT")
        except Exception:
            self._conn.execute("ROLLBACK")
            raise
        return self.get(task_id)

    # ── IDR-017: Non-cascade contract ──
    # This method invalidates ONLY the single specified task. It does NOT:
    #   1. Cascade to downstream dependents (tasks that depend on this task).
    #   2. Check whether any downstream dependent is currently RUNNING.
    # Full cascade semantics per v4 §7 rule 4 are deferred to the reconcile
    # loop (§8), which is out of Phase 1 scope (P3 roadmap deliverable).
    # See IDR-017 for the full decision and gap documentation.
    def invalidate(
        self,
        task_id: str,
        caused_by: str = "controller",
        reason: str = "upstream artifact changed",
    ) -> dict:
        """Invalidate a SUCCEEDED task (v4 §7 rule 4).

        The old result stays archived — never deleted, never overwritten.
        Raises if the task is not in a SUCCEEDED status.

        F-01: Read + validate INSIDE BEGIN IMMEDIATE.

        Scope (IDR-017): invalidates only this single task; does not cascade
        to downstream dependents or check whether a dependent is RUNNING.
        Full cascade is deferred to the reconcile loop (§8, P3).
        """
        ts = self._clock()
        correlation_id = str(uuid.uuid4())

        self._conn.execute("BEGIN IMMEDIATE")
        try:
            from_status = self.get_status(task_id)
            if from_status != TaskStatus.SUCCEEDED:
                raise TaskTransitionError(
                    from_status, TaskStatus.INVALIDATED,
                    "only SUCCEEDED tasks can be invalidated",
                )

            row = self._conn.execute(
                "SELECT project_id FROM tasks WHERE task_id = ?", (task_id,)
            ).fetchone()
            if row is None:
                raise NotFoundError(f"Task not found: {task_id}")
            project_id = row["project_id"]

            self._conn.execute(
                "UPDATE tasks SET status = ?, completed_at = ? WHERE task_id = ?",
                (TaskStatus.INVALIDATED.value, ts, task_id),
            )
            self._append_event(
                event_type="TaskInvalidated",
                project_id=project_id,
                task_id=task_id,
                from_state=from_status.value,
                to_state=TaskStatus.INVALIDATED.value,
                correlation_id=correlation_id,
                caused_by=caused_by,
                reason=reason,
            )
            self._conn.execute("COMMIT")
        except Exception:
            self._conn.execute("ROLLBACK")
            raise
        return self.get(task_id)

    def heartbeat(self, task_id: str) -> None:
        """Update last_heartbeat timestamp (v4 §19 liveness)."""
        ts = self._clock()
        self._conn.execute(
            "UPDATE tasks SET last_heartbeat = ? WHERE task_id = ?",
            (ts, task_id),
        )

    def list_for_project(self, project_id: str, iteration: int | None = None) -> list[dict]:
        if iteration is not None:
            rows = self._conn.execute(
                "SELECT * FROM tasks WHERE project_id = ? AND iteration = ? ORDER BY created_at",
                (project_id, iteration),
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT * FROM tasks WHERE project_id = ? ORDER BY created_at",
                (project_id,),
            ).fetchall()
        return [dict(r) for r in rows]

    def _append_event(self, event_type, project_id=None, task_id=None,
                      from_state=None, to_state=None, correlation_id="",
                      caused_by="", reason="", artifact_ids=None, payload=None):
        """Insert an event row. Called within an existing transaction.

        ADD-01: Delegates to the shared module-level ``_append_event_to_db``.
        F-04: Validates event at the persistence boundary (S6) before INSERT.
        """
        _append_event_to_db(
            self._conn, self._clock, event_type, project_id, task_id,
            from_state, to_state, correlation_id, caused_by, reason,
            artifact_ids, payload,
        )


# ── Event Repository (append-only) ──

class EventRepository:
    """Append-only read/write for the event journal (v4 §8.1).

    Only ``append`` (internal use by Project/Task repos) and ``read`` methods
    are exposed. No update or delete. The journal is the audit trail.
    """

    def __init__(self, conn: sqlite3.Connection):
        self._conn = conn

    def list_for_project(self, project_id: str) -> list[dict]:
        rows = self._conn.execute(
            "SELECT * FROM events WHERE project_id = ? ORDER BY event_id ASC",
            (project_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    def list_for_task(self, task_id: str) -> list[dict]:
        rows = self._conn.execute(
            "SELECT * FROM events WHERE task_id = ? ORDER BY event_id ASC",
            (task_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    def list_all(self) -> list[dict]:
        rows = self._conn.execute(
            "SELECT * FROM events ORDER BY event_id ASC"
        ).fetchall()
        return [dict(r) for r in rows]

    def count(self) -> int:
        row = self._conn.execute("SELECT COUNT(*) as n FROM events").fetchone()
        return row["n"] if row else 0

    def payload_json(
        self,
        event_type: str,
        correlation_id: str,
        project_id: str | None = None,
    ) -> str | None:
        """The RAW payload_json of one journal row, or None when absent —
        a read primitive (B7: the gateway consumes reads through the
        repository, never raw SQL). The caller parses; a corrupt JSON is
        the caller's fail-closed decision, never swallowed here."""
        if project_id is None:
            row = self._conn.execute(
                "SELECT payload_json FROM events "
                "WHERE event_type = ? AND correlation_id = ?",
                (event_type, correlation_id)).fetchone()
        else:
            row = self._conn.execute(
                "SELECT payload_json FROM events "
                "WHERE event_type = ? AND correlation_id = ? "
                "  AND project_id = ?",
                (event_type, correlation_id, project_id)).fetchone()
        return row["payload_json"] if row is not None else None

    def event_exists(self, event_type: str, correlation_id: str) -> bool:
        """True iff a journal row with this (type, correlation) exists."""
        row = self._conn.execute(
            "SELECT 1 FROM events WHERE event_type = ? AND correlation_id = ?",
            (event_type, correlation_id)).fetchone()
        return row is not None

    def append_transactional(
        self,
        clock: Clock,
        event_type: str,
        *,
        project_id: str | None,
        correlation_id: str,
        caused_by: str,
        reason: str = "",
        payload: dict | None = None,
        retry_without_project: bool = False,
    ) -> None:
        """Append one journal row inside ITS OWN transaction — the gateway's
        audit/decision writes now live here (B7), replacing the manual
        BEGIN/COMMIT/ROLLBACK the gateway used to hold. ``retry_without_project``
        mirrors the audit-write's stale-project fallback: on an FK failure
        the row is re-attempted with project_id=NULL (the record of a
        rejected/stale admission still lands in the journal)."""
        import sqlite3 as _sqlite3
        self._conn.execute("BEGIN")
        try:
            try:
                _append_event_to_db(
                    self._conn, clock, event_type,
                    project_id=project_id, correlation_id=correlation_id,
                    caused_by=caused_by, reason=reason, payload=payload,
                )
            except _sqlite3.IntegrityError:
                if not retry_without_project:
                    raise
                self._conn.execute("ROLLBACK")
                self._conn.execute("BEGIN")
                _append_event_to_db(
                    self._conn, clock, event_type,
                    project_id=None, correlation_id=correlation_id,
                    caused_by=caused_by, reason=reason, payload=payload,
                )
            self._conn.execute("COMMIT")
        except Exception:
            self._conn.execute("ROLLBACK")
            raise


# ── Artifact Repository ──

class ArtifactRepository:
    """Read/write artifact metadata in SQLite (content lives on filesystem).

    The artifact store (artifacts/store.py) writes content to the filesystem
    first, then calls this repository to record metadata within a DB
    transaction (IDR-013). If the DB commit fails, the artifact content is
    orphaned but safe (no DB record = cannot be cited).
    """

    def __init__(self, conn: sqlite3.Connection, clock: Clock | None = None):
        self._conn = conn
        self._clock = clock or utc_now

    def record(
        self,
        artifact_id: str,
        artifact_type: str,
        content_hash: str,
        size_bytes: int,
        storage_path: str,
        producer: str,
        project_id: str | None = None,
        task_id: str | None = None,
        metadata: dict | None = None,
    ) -> dict:
        """Insert an artifact metadata record. Fails on duplicate content_hash."""
        ts = self._clock()
        self._conn.execute(
            """INSERT INTO artifacts
               (artifact_id, project_id, task_id, artifact_type,
                content_hash, size_bytes, storage_path, producer,
                metadata_json, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                artifact_id, project_id, task_id, artifact_type,
                content_hash, size_bytes, storage_path, producer,
                _json_dumps(metadata or {}),
                ts,
            ),
        )
        return self.get(artifact_id)

    def get(self, artifact_id: str) -> dict:
        row = self._conn.execute(
            "SELECT * FROM artifacts WHERE artifact_id = ?", (artifact_id,)
        ).fetchone()
        if row is None:
            raise NotFoundError(f"Artifact not found: {artifact_id}")
        d = dict(row)
        d["metadata"] = _json_loads(d.pop("metadata_json")) or {}
        return d

    def get_by_hash(self, content_hash: str) -> dict | None:
        """Return the artifact with the given content hash, or None."""
        row = self._conn.execute(
            "SELECT * FROM artifacts WHERE content_hash = ?", (content_hash,)
        ).fetchone()
        if row is None:
            return None
        d = dict(row)
        d["metadata"] = _json_loads(d.pop("metadata_json")) or {}
        return d

    def list_for_project(self, project_id: str) -> list[dict]:
        rows = self._conn.execute(
            "SELECT * FROM artifacts WHERE project_id = ? ORDER BY created_at",
            (project_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    def exists(self, content_hash: str) -> bool:
        return self.get_by_hash(content_hash) is not None

    def metadata_json_by_hash(
        self,
        project_id: str,
        artifact_type: str,
        content_hash: str,
    ) -> str | None:
        """The RAW metadata_json of the (project, type, hash) artifact row,
        or None when absent (B7: the gateway's classification-metadata reads
        go through the repository). Raw on purpose — the caller decides
        corrupt-JSON handling fail-closed; nothing is swallowed here."""
        row = self._conn.execute(
            "SELECT metadata_json FROM artifacts "
            "WHERE project_id = ? AND artifact_type = ? AND content_hash = ?",
            (project_id, artifact_type, content_hash)).fetchone()
        return row["metadata_json"] if row is not None else None

    def in_project(self, artifact_id: str, project_id: str) -> bool:
        """True iff the artifact exists in this project (B7: the gateway's
        artifact-existence checks go through the repository)."""
        row = self._conn.execute(
            "SELECT 1 FROM artifacts WHERE artifact_id = ? AND project_id = ?",
            (artifact_id, project_id)).fetchone()
        return row is not None


# ── Dataset Manifest Repository (B7: gateway manifest reads) ──

class DatasetManifestRepository:
    """Read-only existence over ``dataset_manifests`` — the gateway's
    EXTRACT source dereference (IDR-028 criterion 7) lives here instead of
    raw SQL in the admission path."""

    def __init__(self, conn: sqlite3.Connection):
        self._conn = conn

    def exists_in_project(self, manifest_id: str, project_id: str) -> bool:
        row = self._conn.execute(
            "SELECT 1 FROM dataset_manifests "
            "WHERE manifest_id = ? AND project_id = ?",
            (manifest_id, project_id)).fetchone()
        return row is not None


# ── Operator Credential Repository (red-team A4) ──

# P2 #1 remediation: the operator token is no longer stored as a bare
# SHA-256 (trivially fast to brute-force if the DB leaks). The stored value
# is a self-describing salted PBKDF2-HMAC-SHA256 hash:
#
#     pbkdf2$sha256$<iterations>$<salt_hex>$<hash_hex>
#
# — the per-credential RANDOM salt defeats rainbow/precomputation tables
# across leaked rows, and the iterations make each offline guess expensive.
# The iterations are part of the stored value, so the work factor can be
# raised later without a schema change. Bare-hex values (pre-remediation
# rows) verify through a legacy SHA-256 fallback so existing databases keep
# working.
_OPERATOR_TOKEN_HASH_PREFIX = "pbkdf2$sha256$"
_OPERATOR_TOKEN_ITERATIONS = 210_000
_OPERATOR_TOKEN_MIN_LENGTH = 8
# F2 (audit): the presented token is bounded to this many characters —
# PBKDF2's per-iteration cost scales with the password length, so an
# unbounded token would let an attacker force arbitrarily expensive KDF
# work per verify. The bound is checked BEFORE any hashing (register and
# verify), so the per-verify KDF cost is constant and the refusal leaks
# nothing (it depends only on the attacker-known token length, never on
# stored state).
_OPERATOR_TOKEN_MAX_LENGTH = 1024
# F2/F4 (audit): the stored credential hash is bound to this many bytes — a
# legitimate row is ~120 chars (prefix + 6-digit iterations + 32-hex salt +
# 64-hex digest), so 512 is generous headroom. The bound runs BEFORE any
# parse (split / int / bytes.fromhex), so a tampered row with a gigantic
# salt or digest cannot force variable-cost parse work into the verify
# path: the shape check itself is O(MAX) constant, never O(stored length).
_OPERATOR_TOKEN_HASH_MAX_BYTES = 512
# F4 (audit): the stored iteration count is honored only inside this sane
# range. An attacker who can rewrite the stored row must not be able to
# hang every operator verdict with an astronomical work factor (stored-
# iteration DoS) or trivially weaken verification with a degenerate one.
_OPERATOR_TOKEN_ITERATIONS_MIN = 100_000
_OPERATOR_TOKEN_ITERATIONS_MAX = 10_000_000


def _operator_token_hash(token: str) -> str:
    """Salted PBKDF2-HMAC-SHA256 of the plaintext operator token — the ONLY
    thing stored. The token itself exists only at the operator's hand. A
    fresh 128-bit random salt is drawn per call (the salt travels inside the
    stored value; verification re-derives from it)."""
    import hashlib
    import secrets
    salt = secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac(
        "sha256", token.encode("utf-8"), salt, _OPERATOR_TOKEN_ITERATIONS)
    return (f"{_OPERATOR_TOKEN_HASH_PREFIX}{_OPERATOR_TOKEN_ITERATIONS}"
            f"${salt.hex()}${dk.hex()}")


# F2 (audit): a lazily-built dummy credential hash — a valid
# self-describing PBKDF2 value with a FIXED salt, used to burn the same
# verification work on the unknown-operator path so a stopwatch cannot
# enumerate operator_ids. Built once; the presented token is hashed with
# the stored (fixed) parameters on every call.
_OPERATOR_DUMMY_HASH: str | None = None


def _burn_dummy_operator_work(token: str) -> None:
    """Constant-work branch for an unknown operator_id (F2 audit): the
    caller pays the same PBKDF2 cost as a real verification, so response
    time does not leak whether the id exists. The result is always False
    at the call site — this only equalizes the work."""
    global _OPERATOR_DUMMY_HASH
    if _OPERATOR_DUMMY_HASH is None:
        _OPERATOR_DUMMY_HASH = _operator_token_hash(
            "hermes-unknown-operator-dummy")
    _token_hash_matches(_OPERATOR_DUMMY_HASH, token)


def _token_hash_matches(stored: str, token: str) -> bool:
    """Constant-time check of ``token`` against a stored credential hash.

    New-style rows carry the self-describing ``pbkdf2$...`` value and are
    re-derived with the STORED salt + iterations. Legacy rows (bare 64-hex
    SHA-256, pre-P2 #1) fall back to the old comparison so existing
    databases keep verifying. Never raises: an unparseable stored value
    simply does not match (fail-closed)."""
    import hashlib
    import hmac
    if len(stored) > _OPERATOR_TOKEN_HASH_MAX_BYTES:
        return False  # bound the parse before any work on tampered fields
    if stored.startswith(_OPERATOR_TOKEN_HASH_PREFIX):
        try:
            _prefix, alg, iterations, salt_hex, hash_hex = stored.split("$")
            if alg != "sha256":
                return False
            iters = int(iterations)
            if not (_OPERATOR_TOKEN_ITERATIONS_MIN <= iters
                    <= _OPERATOR_TOKEN_ITERATIONS_MAX):
                return False  # F4: out-of-range work factor never honored
            salt = bytes.fromhex(salt_hex)
            if len(salt) != 16 or len(hash_hex) != 64:
                return False  # strict shape: 128-bit salt, SHA-256 digest
            dk = hashlib.pbkdf2_hmac(
                "sha256", token.encode("utf-8"), salt, iters)
        except ValueError:
            return False
        return hmac.compare_digest(hash_hex, dk.hex())
    # legacy bare-hex SHA-256 (pre-P2 #1 rows): compared ONLY when the
    # stored value is a well-formed 64-hex digest — anything else fails
    # closed and NEVER raises (hmac.compare_digest rejects non-ASCII str,
    # so a tampered non-ASCII row must simply not match, not crash the
    # verify).
    if len(stored) == 64:
        try:
            bytes.fromhex(stored)
        except ValueError:
            return False
        return hmac.compare_digest(
            stored, hashlib.sha256(token.encode("utf-8")).hexdigest())
    return False


class OperatorCredentialRepository:
    """Ratified proof-of-humanity credentials (red-team A4): an operator
    registers once through the controller's bootstrap surface, and every
    operator verdict (``resolve_human_gate`` / ``record_operator_decision``)
    must present the operator_id AND the matching plaintext token. Only a
    salted PBKDF2-HMAC-SHA256 hash of the token is persisted — a DB leak
    never leaks a usable credential, and offline brute-force is expensive.
    Registration is idempotent for the same (id, token); a different token
    for an existing id is refused (the credential is ratifiable, not
    overwriteable)."""

    def __init__(self, conn: sqlite3.Connection, clock: Clock | None = None):
        self._conn = conn
        self._clock = clock or utc_now

    def register(self, operator_id: str, token: str, name: str) -> dict:
        if len(token) < _OPERATOR_TOKEN_MIN_LENGTH:
            raise ValueError(
                f"token must be at least {_OPERATOR_TOKEN_MIN_LENGTH} "
                f"characters (got {len(token)})")
        if len(token) > _OPERATOR_TOKEN_MAX_LENGTH:
            raise ValueError(
                f"token must be at most {_OPERATOR_TOKEN_MAX_LENGTH} "
                f"characters (got {len(token)})")
        existing = self._conn.execute(
            "SELECT token_hash FROM operator_credentials "
            "WHERE operator_id = ?", (operator_id,)).fetchone()
        if existing is not None:
            # Idempotency is a VERIFY (constant-time, salt-aware): the same
            # token re-presented returns the existing row; a different token
            # is refused — the credential is ratifiable, not overwriteable.
            if _token_hash_matches(existing["token_hash"], token):
                row = self._conn.execute(
                    "SELECT operator_id, name, created_at "
                    "FROM operator_credentials WHERE operator_id = ?",
                    (operator_id,)).fetchone()
                return dict(row)
            raise ValueError(
                f"operator {operator_id!r} already registered with a "
                f"different token — the credential is ratifiable, not "
                f"overwriteable")
        ts = self._clock()
        self._conn.execute(
            "INSERT INTO operator_credentials "
            "(operator_id, token_hash, name, created_at) "
            "VALUES (?, ?, ?, ?)",
            (operator_id, _operator_token_hash(token), name, ts))
        return {"operator_id": operator_id, "name": name, "created_at": ts}

    def verify(self, operator_id: str, token: str) -> bool:
        """Constant-time comparison of the presented token's hash against
        the stored hash. False for an unknown operator (fail-closed). An
        oversized token (beyond ``_OPERATOR_TOKEN_MAX_LENGTH``) is refused
        BEFORE any hashing — the per-verify KDF cost stays bounded, and the
        refusal reveals nothing (the length is the presenter's own input)."""
        if len(token) > _OPERATOR_TOKEN_MAX_LENGTH:
            return False
        row = self._conn.execute(
            "SELECT token_hash FROM operator_credentials "
            "WHERE operator_id = ?", (operator_id,)).fetchone()
        if row is None:
            # F2 (audit): equalize the work — never reveal id existence by
            # response time. Still False, fail-closed.
            _burn_dummy_operator_work(token)
            return False
        return _token_hash_matches(row["token_hash"], token)

    def exists(self, operator_id: str) -> bool:
        row = self._conn.execute(
            "SELECT 1 FROM operator_credentials WHERE operator_id = ?",
            (operator_id,)).fetchone()
        return row is not None


# ── ResearchProgram Repository (IDR-018: approved Part 2 architecture) ──

class ResearchProgramError(Exception):
    """Raised when a ResearchProgram write violates the approved contract.

    The program is a proposal artifact: only a ``COMPILED`` result may be
    persisted, the scope brief must exist (governance), supersession must
    reference the current head, and nothing is ever updated or deleted.
    """


class ResearchProgramIntegrityError(ResearchProgramError):
    """A claimed COMPILED program whose identity or derived state is self-inconsistent.

    Raised at the persistence boundary when the caller-supplied identity
    (``content_hash``, ``program_id``, ``input_hash``, ``schema_version``) or
    the derived obligations do not match the canonical derivation shared with
    the compiler (EC-V6-11..16, v6 §28.2 Model D integrity checks). Fail-closed:
    nothing is written and no event is emitted. Distinct from a compilation
    verdict: this is an integrity violation at the write path, not semantics.
    """


class ResearchProgramRepository:
    """Read/write the immutable ``ResearchProgram`` artifact (v4 §16.1 pattern).

    The write path is the persistence implementation of the gateway's
    ``PROPOSE_RESEARCH_PROGRAM`` per-kind validator (the gateway itself lands
    at P3, like the other §8 validators). Defenses-in-depth, in order:

    1. Only ``COMPILED`` results are accepted — there is no write path for an
       unvalidated program (Part 2 E6/E7; the "no direct mutation bypass"
       adversarial test).
    2. The frozen ``ScopeBrief`` must exist for the project (governance,
       v4 §6.1/S16) — resolved here, never trusted from the caller.
    3. Supersession must reference the project's current chain head and must
       change content (E9: a new version, never a silent mutation).
    4. Idempotency: a duplicate compilation (same project + content hash)
       returns the existing row and emits no duplicate event (PA4 pattern).
    5. No UPDATE/DELETE path exists at all — immutability is structural.
    """

    def __init__(self, conn: sqlite3.Connection, clock: Clock | None = None):
        self._conn = conn
        self._clock = clock or utc_now

    # ── governance context for the validator ──

    def resolve_scope_content_hash(self, project_id: str, scope_ref: str) -> str:
        """Return the frozen ScopeBrief's content hash, or raise.

        The program must cite a frozen brief of this project (v4 §6.1/S16).
        This is the governance context ``compile_research_program`` requires.
        """
        row = self._conn.execute(
            "SELECT content_hash FROM scope_briefs "
            "WHERE brief_id = ? AND project_id = ?",
            (scope_ref, project_id),
        ).fetchone()
        if row is None:
            raise ResearchProgramError(
                f"ScopeBrief not found: {scope_ref!r} for project {project_id!r} — "
                f"a ResearchProgram must cite the frozen brief (v4 §6.1/S16)"
            )
        return row["content_hash"]

    def superseded_program_ids(
        self, project_id: str, supersedes_ref: str | None,
    ) -> frozenset[str]:
        """Validation context: the program ids a supersession may reference.
        Only the project's current chain head qualifies (E9 — a new version
        supersedes the head only)."""
        if supersedes_ref is None:
            return frozenset()
        row = self._conn.execute(
            "SELECT program_id FROM research_programs "
            "WHERE program_id = ? AND project_id = ?",
            (supersedes_ref, project_id),
        ).fetchone()
        if row is None:
            raise ResearchProgramError(
                f"Supersede target not found: {supersedes_ref!r} for project "
                f"{project_id!r}"
            )
        current = self.current(project_id)
        if current is None or current["program_id"] != supersedes_ref:
            raise ResearchProgramError(
                f"Supersede target {supersedes_ref!r} is not the project's "
                f"current program head — a new version supersedes the head only "
                f"(IDR-018, E9)"
            )
        return frozenset({row["program_id"]})

    def known_program_ids(self, project_id: str) -> frozenset[str]:
        """Validation context: the program ids a parent_program_id may reference.

        All persisted program_ids for this project (ADR-041 parallel-regime-test
        linkage). Resolved here, never trusted from the caller — a parent_program_id
        that does not reference a real program of this project is rejected at the
        persistence boundary.
        """
        rows = self._conn.execute(
            "SELECT program_id FROM research_programs WHERE project_id = ?",
            (project_id,),
        ).fetchall()
        return frozenset({row["program_id"] for row in rows})

    def known_hypothesis_refs(self, project_id: str) -> frozenset[str]:
        """Validation context: hypothesis refs a parent_hypothesis_ref may reference.

        The union of all hypothesis ``ref`` values across all persisted program
        versions in this project (ADR-041 parallel-regime-test linkage). Resolved
        here, never trusted from the caller — a parent_hypothesis_ref that does not
        reference a real hypothesis of this project is rejected at the persistence
        boundary.
        """
        refs: set[str] = set()
        rows = self._conn.execute(
            "SELECT hypothesis_json FROM research_programs WHERE project_id = ?",
            (project_id,),
        ).fetchall()
        for row in rows:
            hypotheses = _json_loads(row["hypothesis_json"])
            if isinstance(hypotheses, list):
                for h in hypotheses:
                    if isinstance(h, dict):
                        ref = h.get("ref")
                        if isinstance(ref, str):
                            refs.add(ref)
        return frozenset(refs)

    # ── the write path ──

    def record(
        self,
        project_id: str,
        result: CompilationResult,
        *,
        produced_by: str = "director",
        reason: str = "",
        new_slot_declarations: Sequence[dict] = (),
    ) -> dict:
        """Persist a compiled program atomically with its event (IDR-013).

        C1 (design gate §4.4/§5.2, AC-5): ``new_slot_declarations`` is the
        payload-only admission-time evidence for vocabulary growth — a
        sequence of ``{"slot_ref", "rationale"}`` dicts, already validated
        by E6 at compile. It is recorded in the append-only admission event
        payload (the audit IS the record, IDR-040 precedent) and is NEVER
        part of ``canonical_content_dict`` — it never alters
        ``content_hash``. Default empty: a slot-less program records
        exactly as before C1 (Delta=0).

        Raises ``ResearchProgramError`` for any contract violation and
        ``ResearchProgramIntegrityError`` when the claimed COMPILED object's
        identity fields or derived obligations do not match the canonical
        derivation (v6 §28.2 Model D integrity checks — fail-closed, nothing
        written, no event). Returns the existing row for a duplicate genuine
        compilation (idempotent, no event).
        """
        from hermes.research.programs import program_to_dict

        # 1. Only COMPILED programs have a write path (E6/E7).
        if not result.compiled or result.program is None:
            raise ResearchProgramError(
                f"refusing to persist a non-COMPILED program "
                f"(status={result.status.value}) — no write path for "
                f"unvalidated programs (IDR-018)"
            )
        program = result.program
        if program.project_id != project_id:
            raise ResearchProgramError(
                f"program project {program.project_id!r} does not match "
                f"{project_id!r}"
            )

        # 2. Governance: the frozen brief must exist AND the program must have
        #    been compiled against that brief's actual content hash (R-02).
        #    Resolved here, never trusted from the caller — a program compiled
        #    with a bogus/stale scope hash is rejected at the write path.
        resolved_scope_hash = self.resolve_scope_content_hash(
            project_id, program.scope_ref)
        if program.scope_content_hash != resolved_scope_hash:
            raise ResearchProgramError(
                f"program was compiled against scope content hash "
                f"{program.scope_content_hash!r} but the frozen brief "
                f"{program.scope_ref!r} hashes to {resolved_scope_hash!r} — "
                f"recompile against the actual frozen brief (R-02, IDR-018)"
            )

        # 2b. Integrity boundary (v6 §28.2, Model D): the repository does NOT
        #     re-run the epistemic validator, but it never blindly trusts a
        #     caller-claimed COMPILED object. Identity fields and derived
        #     obligations are re-derived with the SAME pure helpers the
        #     compiler uses — one deterministic derivation, never two
        #     (EC-V6-11..16). Checks self-consistency of the artifact, not its
        #     semantics: the validator stays the epistemic authority and the
        #     gateway the P3 admission authority. Fail-closed: any mismatch
        #     raises before the transaction, so no row and no event.
        from hermes.research.programs import (
            SUPPORTED_PROGRAM_SCHEMA_VERSIONS,
            content_hash_of,
            derive_program_obligations,
            input_hash_of,
            program_id_of,
            validate_program_epistemic,
        )
        recomputed_content_hash = content_hash_of(program)
        if program.content_hash != recomputed_content_hash:
            raise ResearchProgramIntegrityError(
                f"content_hash {program.content_hash!r} does not match the "
                f"canonical content identity {recomputed_content_hash!r} — "
                f"identity is derived, never authored (EC-V6-11, v6 §28.2)"
            )
        expected_program_id = program_id_of(recomputed_content_hash)
        if program.program_id != expected_program_id:
            raise ResearchProgramIntegrityError(
                f"program_id {program.program_id!r} is not the content-derived "
                f"identity {expected_program_id!r} — identity is derived, "
                f"never authored (EC-V6-11, v6 §28.2)"
            )
        if program.input_hash != input_hash_of(program):
            raise ResearchProgramIntegrityError(
                "input_hash does not match the canonical input identity — "
                "forged or stale identity (EC-V6-13, v6 §28.2)"
            )
        if program.schema_version not in SUPPORTED_PROGRAM_SCHEMA_VERSIONS:
            raise ResearchProgramIntegrityError(
                f"schema_version {program.schema_version!r} is not one of "
                f"the supported versions "
                f"{sorted(SUPPORTED_PROGRAM_SCHEMA_VERSIONS)!r} — a program "
                f"the validator would reject as INVALID cannot be persisted "
                f"(EC-V6-15, v6 §28.2; C1 ratified Option A)"
            )
        expected_evidence, expected_gates = derive_program_obligations(
            program.hypotheses)
        if (program.evidence_requirements != expected_evidence
                or program.gate_requirements != expected_gates):
            raise ResearchProgramIntegrityError(
                "declared evidence/gate requirements do not match the "
                "hypotheses-derived obligations — obligations are derived by "
                "the validator, never declared (EC-V6-14, v6 §28.2)"
            )

        # 2c. Epistemic re-validation (AR-01 hardening): the integrity
        #     boundary above re-derives identity and obligations but not the
        #     prediction-level epistemic checks (E1/E4/E5 + contradiction
        #     rule) — predictions do not feed the obligation derivation, so a
        #     forged-but-self-consistent program could omit them without
        #     tripping EC-V6-11..16. Re-run the pure E-checks on the program
        #     itself (the same logic the compiler applies to the draft): any
        #     error fails closed here, at the write path, before any row or
        #     event. This is defense-in-depth, not a second validator — the
        #     compiler remains the epistemic authority; the repository merely
        #     refuses to persist a program whose own content violates the
        #     checks it must satisfy to have been COMPILED.
        epistemic_errors = validate_program_epistemic(program)
        if epistemic_errors:
            reasons = "; ".join(
                f"{e.code}@{e.field_path}: {e.explanation}"
                for e in epistemic_errors)
            raise ResearchProgramIntegrityError(
                f"refusing to persist a program whose own content violates "
                f"the epistemic checks (AR-01 write-path re-validation): "
                f"{reasons}"
            )

        # 2d. C1 slot-discipline re-validation (adversarial closure gate):
        #     E6 is a closed-vocabulary + format check consumed by the gateway
        #     via the ``slot_vocabulary`` projection. The repository never
        #     blindly trusts a caller-claimed COMPILED object that bypasses
        #     the gateway — a forged program that carries a malformed, over-
        #     long, undeclared, already-declared, or orphan-declared slot
        #     would otherwise poison the append-only vocabulary (the vocabulary
        #     is the union over persisted rows, so a poisoned row permanently
        #     pollutes every future E6 decision). Re-run the exact E6 logic
        #     here using the repository's own vocabulary projection as the
        #     source of truth, fail-closed before any row or event. This is
        #     the same defense-in-depth pattern as AR-01: the validator stays
        #     the admission authority; the repository is the integrity boundary.
        from hermes.research.programs import (
            _SLOT_REF_MAX_LENGTH,
            _SLOT_REF_RE,
            MAX_SLOT_RATIONALE,
        )
        # — format of every carried slot_ref —
        used_slots_write: dict[str, str] = {}
        for h in program.hypotheses:
            slot = h.slot_ref
            if slot is None:
                continue
            if (not isinstance(slot, str)
                    or not _SLOT_REF_RE.match(slot)
                    or len(slot) > _SLOT_REF_MAX_LENGTH):
                raise ResearchProgramIntegrityError(
                    f"refusing to persist a program whose hypothesis "
                    f"{h.ref!r} carries a malformed slot_ref "
                    f"{slot!r} — E6_SLOT_MALFORMED at the write path "
                    f"(C1 §2.2; slot_ref must be "
                    f"'slot:<snake_case_label>', ASCII, at most "
                    f"{_SLOT_REF_MAX_LENGTH} characters)"
                )
            used_slots_write.setdefault(slot, h.ref)
        # — payload-only declarations carried as the admission evidence —
        # Fail-closed on shape: the gateway validates this shape before
        # compile; a direct record bypass can carry any Sequence[dict].
        declared_slots_write: dict[str, dict] = {}
        for idx, decl in enumerate(new_slot_declarations):
            if not isinstance(decl, dict):
                raise ResearchProgramIntegrityError(
                    f"refusing to persist a program with a malformed "
                    f"new_slot_declarations[{idx}] entry — expected a dict "
                    f"with 'slot_ref' and 'rationale' (C1 §4.4, "
                    f"E6 write-path re-validation)"
                )
            slot_ref = decl.get("slot_ref")
            rationale = decl.get("rationale")
            unknown = set(decl.keys()) - {"slot_ref", "rationale"}
            if unknown:
                raise ResearchProgramIntegrityError(
                    f"refusing to persist a program with unknown keys "
                    f"{sorted(unknown)} in new_slot_declarations[{idx}] — "
                    f"the slot declaration schema is closed (E6 write-path)"
                )
            if (not isinstance(slot_ref, str)
                    or not _SLOT_REF_RE.match(slot_ref)
                    or len(slot_ref) > _SLOT_REF_MAX_LENGTH):
                raise ResearchProgramIntegrityError(
                    f"refusing to persist a program with a malformed "
                    f"declared slot_ref {slot_ref!r} at "
                    f"new_slot_declarations[{idx}] — "
                    f"E6_SLOT_MALFORMED at the write path"
                )
            if not isinstance(rationale, str) or not rationale.strip():
                raise ResearchProgramIntegrityError(
                    f"refusing to persist a program with a malformed "
                    f"rationale at new_slot_declarations[{idx}] — "
                    f"rationale must be a non-empty string "
                    f"(E6 write-path)"
                )
            if len(rationale) > MAX_SLOT_RATIONALE:
                raise ResearchProgramIntegrityError(
                    f"refusing to persist a program with an over-long "
                    f"rationale at new_slot_declarations[{idx}] — "
                    f"at most {MAX_SLOT_RATIONALE} characters "
                    f"(E6 write-path)"
                )
            if slot_ref in declared_slots_write:
                raise ResearchProgramIntegrityError(
                    f"refusing to persist a program that declares "
                    f"{slot_ref!r} twice in the same payload — "
                    f"E6_SLOT_MALFORMED at the write path (duplicate "
                    f"declaration)"
                )
            # vocabulary as the source of truth — fail-closed if corrupt
            try:
                vocab_for_decl = self.slot_vocabulary(project_id)
            except ResearchProgramError:
                raise
            except Exception as exc:
                raise ResearchProgramIntegrityError(
                    f"refusing to persist a program whose project "
                    f"{project_id!r} has a corrupt slot vocabulary — "
                    f"fail-closed rather than shrinking the vocabulary "
                    f"(AC-7, E6 write-path): {exc}"
                ) from exc
            if slot_ref in vocab_for_decl:
                raise ResearchProgramIntegrityError(
                    f"refusing to persist a program that re-declares "
                    f"{slot_ref!r} already in the project vocabulary — "
                    f"E6_SLOT_ALREADY_DECLARED at the write path (C1 §4.3)"
                )
            declared_slots_write[slot_ref] = decl
        # — vocabulary membership in both directions —
        try:
            current_vocab = self.slot_vocabulary(project_id)
        except ResearchProgramError:
            raise
        except Exception as exc:
            raise ResearchProgramIntegrityError(
                f"refusing to persist a program whose project "
                f"{project_id!r} has a corrupt slot vocabulary — "
                f"fail-closed (AC-7, E6 write-path): {exc}"
            ) from exc
        for slot, hyp_ref in sorted(used_slots_write.items()):
            if slot not in current_vocab and slot not in declared_slots_write:
                raise ResearchProgramIntegrityError(
                    f"refusing to persist a program whose hypothesis "
                    f"{hyp_ref!r} uses slot {slot!r} not in the project "
                    f"vocabulary and not declared new in this payload — "
                    f"E6_SLOT_UNDECLARED at the write path (C1 §4.3/§4.5)"
                )
        for slot in sorted(declared_slots_write):
            if slot not in used_slots_write:
                raise ResearchProgramIntegrityError(
                    f"refusing to persist a program whose declaration of "
                    f"{slot!r} is not used by any hypothesis in the same "
                    f"payload — E6_SLOT_DECLARATION_UNUSED at the write path"
                )

        ts = self._clock()
        correlation_id = str(uuid.uuid4())

        self._conn.execute("BEGIN IMMEDIATE")
        try:
            # 4. Idempotency: an identical program for this project already
            #    exists → return it, no duplicate event (PA4 pattern) — but a
            #    *supersession* with unchanged content is meaningless and must
            #    fail loudly rather than silently drop the supersede intent
            #    (E9: a new version changes the contract).
            existing = self._conn.execute(
                "SELECT * FROM research_programs "
                "WHERE project_id = ? AND content_hash = ?",
                (project_id, program.content_hash),
            ).fetchone()
            if existing is not None:
                if program.supersedes_ref is not None:
                    self._conn.execute("ROLLBACK")
                    raise ResearchProgramError(
                        "supersession must change program content — the "
                        "proposed program is identical to the existing one "
                        "(idempotent duplicate; a new version changes the "
                        "contract, IDR-018)"
                    )
                self._conn.execute("COMMIT")
                return _research_program_row_to_dict(existing)

            # 3. Supersession semantics.
            if program.supersedes_ref is not None:
                sup = self._conn.execute(
                    "SELECT * FROM research_programs "
                    "WHERE program_id = ? AND project_id = ?",
                    (program.supersedes_ref, project_id),
                ).fetchone()
                if sup is None:
                    self._conn.execute("ROLLBACK")
                    raise ResearchProgramError(
                        f"Supersede target not found: {program.supersedes_ref!r}"
                    )
                current = self._conn.execute(
                    "SELECT MAX(version) AS v FROM research_programs "
                    "WHERE project_id = ?",
                    (project_id,),
                ).fetchone()
                if sup["version"] != current["v"]:
                    self._conn.execute("ROLLBACK")
                    raise ResearchProgramError(
                        f"Supersede target {program.supersedes_ref!r} is not the "
                        f"current head — new versions supersede the head only (E9)"
                    )
                if sup["content_hash"] == program.content_hash:
                    self._conn.execute("ROLLBACK")
                    raise ResearchProgramError(
                        "supersession must change program content — the "
                        "superseding program is identical to its target"
                    )
                version = sup["version"] + 1
            else:
                head = self._conn.execute(
                    "SELECT MAX(version) AS v FROM research_programs "
                    "WHERE project_id = ?",
                    (project_id,),
                ).fetchone()
                if head["v"] is not None and program.parent_program_id is None:
                    self._conn.execute("ROLLBACK")
                    raise ResearchProgramError(
                        f"project {project_id!r} already has a ResearchProgram "
                        f"(version {head['v']}) — supersede it; a new version is "
                        f"never a silent mutation (IDR-018, E9)"
                    )
                # parallel-regime-test programs get the next version number
                # (v = max+1) — they run alongside, not as replacements, but
                # the UNIQUE(project_id, version) constraint requires a fresh
                # slot.
                version = (head["v"] or 0) + 1 if program.parent_program_id else 1

            pdict = program_to_dict(program)
            self._conn.execute(
                """INSERT INTO research_programs
                   (program_id, project_id, version, content_hash, supersedes_id,
                    scope_ref, epistemic_objective, compiler_version,
                    policy_version, schema_version, input_hash,
                    hypothesis_json, prediction_json, discrimination_json,
                    evidence_json, gate_json, methodology_json,
                    task_graph_template_ref, parent_program_id, parent_hypothesis_ref,
                    target_regime, produced_by, reason, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                           ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    program.program_id, project_id, version, program.content_hash,
                    program.supersedes_ref, program.scope_ref,
                    program.epistemic_objective, program.compiler_version,
                    program.policy_version, program.schema_version,
                    program.input_hash,
                    _json_dumps(pdict["hypotheses"]),
                    _json_dumps(pdict["predictions"]),
                    _json_dumps(pdict["discrimination_requirements"]),
                    _json_dumps(pdict["evidence_requirements"]),
                    _json_dumps(pdict["gate_requirements"]),
                    _json_dumps(pdict["methodology_constraints"]),
                    program.task_graph_template_ref,
                    program.parent_program_id, program.parent_hypothesis_ref,
                    program.target_regime, produced_by, reason, ts,
                ),
            )
            self._append_event(
                event_type="ResearchProgramCompiled",
                project_id=project_id,
                to_state=CompilationStatus.COMPILED.value,
                correlation_id=correlation_id,
                caused_by=produced_by,
                reason=reason,
                artifact_ids=[program.program_id],
                payload={
                    "program_id": program.program_id,
                    "content_hash": program.content_hash,
                    "version": version,
                    "supersedes_ref": program.supersedes_ref,
                    "scope_ref": program.scope_ref,
                    # C1 (AC-5): vocabulary-growth provenance, recorded only
                    # when present — a slot-less admission event stays
                    # byte-identical to its pre-C1 shape.
                    **({"new_slot_declarations": list(new_slot_declarations)}
                       if new_slot_declarations else {}),
                },
            )
            self._conn.execute("COMMIT")
        except Exception:
            if self._conn.in_transaction:
                self._conn.execute("ROLLBACK")
            raise

        row = self._conn.execute(
            "SELECT * FROM research_programs WHERE program_id = ?",
            (program.program_id,),
        ).fetchone()
        return _research_program_row_to_dict(row)

    # ── read side (no update, no delete — immutability is structural) ──

    def get(self, program_id: str) -> dict:
        row = self._conn.execute(
            "SELECT * FROM research_programs WHERE program_id = ?",
            (program_id,),
        ).fetchone()
        if row is None:
            raise NotFoundError(f"ResearchProgram not found: {program_id}")
        return _research_program_row_to_dict(row)

    def get_by_hash(self, content_hash: str) -> dict | None:
        row = self._conn.execute(
            "SELECT * FROM research_programs WHERE content_hash = ?",
            (content_hash,),
        ).fetchone()
        if row is None:
            return None
        return _research_program_row_to_dict(row)

    def current(self, project_id: str) -> dict | None:
        """The head of the project's supersession chain (max version)."""
        row = self._conn.execute(
            "SELECT * FROM research_programs WHERE project_id = ? "
            "ORDER BY version DESC LIMIT 1",
            (project_id,),
        ).fetchone()
        if row is None:
            return None
        return _research_program_row_to_dict(row)

    def current_primary(self, project_id: str) -> dict | None:
        """The head of the project's supersession chain excluding B3C children.

        IDR-045 C1: eligibility for the plan-admission pass is the filtered head
        ``MAX(version) WHERE parent_program_id IS NULL`` (the supersession
        chain head, never a parallel-regime-test child). A B3C child
        (``parent_program_id`` not null) gets ``version = max+1`` but runs
        ``alongside, not as a replacement`` (``repositories.py:1612``); it never
        becomes the primary head and never steals plan admission.
        """
        row = self._conn.execute(
            "SELECT * FROM research_programs WHERE project_id = ? "
            "AND parent_program_id IS NULL ORDER BY version DESC LIMIT 1",
            (project_id,),
        ).fetchone()
        if row is None:
            return None
        return _research_program_row_to_dict(row)

    def list_for_project(self, project_id: str) -> list[dict]:
        rows = self._conn.execute(
            "SELECT * FROM research_programs WHERE project_id = ? "
            "ORDER BY version ASC",
            (project_id,),
        ).fetchall()
        return [_research_program_row_to_dict(r) for r in rows]

    def slot_vocabulary(self, project_id: str) -> frozenset[str]:
        """C1 (design gate §4.3): the project's append-only slot vocabulary.

        The union of ``slot_ref`` values over ALL program versions in the
        project's supersession history (every immutable ``research_programs``
        row) — a read-only projection consumed by E6 via the compile context
        (design gate §5.3). No new table, no write path.

        Pure function of the project's immutable rows (AC-4): identical rows
        ⇒ identical vocabulary, independent of admission order. Slots are
        never retired — a REFUTED or dropped hypothesis's slot remains in
        the vocabulary (the resurrection consumer must recognize it).

        Pre-C1 rows are tolerated: a hypothesis dict with no ``slot_ref``
        key contributes nothing (dual-consumer note, design gate §5.1).

        Fail-closed (AC-7): a corrupt/unresolvable row raises
        ``ResearchProgramError`` rather than silently shrinking the
        vocabulary — a shrunken vocabulary would let E6 mis-admit or
        mis-reject a slot. The gateway converts the raise into a structured
        rejection (reject, never crash).
        """
        slots: set[str] = set()
        rows = self._conn.execute(
            "SELECT hypothesis_json FROM research_programs "
            "WHERE project_id = ? ORDER BY version ASC",
            (project_id,),
        ).fetchall()
        for row in rows:
            try:
                hypotheses = _json_loads(row["hypothesis_json"])
            except ValueError as exc:
                raise ResearchProgramError(
                    f"corrupt research_programs row for project "
                    f"{project_id!r}: hypothesis_json does not parse "
                    f"({exc}) — the C1 slot vocabulary cannot be derived; "
                    f"refusing rather than shrinking the vocabulary (AC-7)"
                ) from exc
            if hypotheses is None:
                continue  # NULL column == no hypotheses == no slots
            if not isinstance(hypotheses, list):
                raise ResearchProgramError(
                    f"corrupt research_programs row for project "
                    f"{project_id!r}: hypothesis_json is not a list — the "
                    f"C1 slot vocabulary cannot be derived (AC-7)"
                )
            for h in hypotheses:
                if not isinstance(h, dict):
                    raise ResearchProgramError(
                        f"corrupt research_programs row for project "
                        f"{project_id!r}: a hypothesis entry is not a dict "
                        f"— the C1 slot vocabulary cannot be derived (AC-7)"
                    )
                slot = h.get("slot_ref")  # tolerate MISSING key (pre-C1 rows)
                if slot is None:
                    continue
                if not isinstance(slot, str):
                    raise ResearchProgramError(
                        f"corrupt research_programs row for project "
                        f"{project_id!r}: a hypothesis slot_ref is not a "
                        f"string — the C1 slot vocabulary cannot be derived "
                        f"(AC-7)"
                    )
                slots.add(slot)
        return frozenset(slots)

    def exists(self, program_id: str) -> bool:
        row = self._conn.execute(
            "SELECT 1 FROM research_programs WHERE program_id = ?",
            (program_id,),
        ).fetchone()
        return row is not None

    def _append_event(self, event_type, project_id=None, task_id=None,
                      from_state=None, to_state=None, correlation_id="",
                      caused_by="", reason="", artifact_ids=None, payload=None):
        """Insert an event row. Called within an existing transaction.

        ADD-01: Delegates to the shared module-level ``_append_event_to_db``.
        F-04: Validates event at the persistence boundary (S6) before INSERT.
        """
        _append_event_to_db(
            self._conn, self._clock, event_type, project_id, task_id,
            from_state, to_state, correlation_id, caused_by, reason,
            artifact_ids, payload,
        )


def _research_program_row_to_dict(row: sqlite3.Row) -> dict:
    """Map a research_programs row to a dict with JSON columns parsed."""
    d = dict(row)
    d["hypotheses"] = _json_loads(d.pop("hypothesis_json")) or []
    d["predictions"] = _json_loads(d.pop("prediction_json")) or []
    d["discrimination_requirements"] = _json_loads(d.pop("discrimination_json")) or []
    d["evidence_requirements"] = _json_loads(d.pop("evidence_json")) or []
    d["gate_requirements"] = _json_loads(d.pop("gate_json")) or []
    d["methodology_constraints"] = _json_loads(d.pop("methodology_json")) or []
    # parallel-regime-test linkage (advisory, read directly from columns).
    d["parent_program_id"] = d.get("parent_program_id")
    d["parent_hypothesis_ref"] = d.get("parent_hypothesis_ref")
    d["target_regime"] = d.get("target_regime")
    return d


def _claim_row_to_dict(row: sqlite3.Row) -> dict:
    """Map a research_claims row to a dict with JSON columns parsed."""
    d = dict(row)
    d["context_tags"] = _json_loads(d.pop("context_tags_json")) or {}
    d["related_claim_ids"] = tuple(
        _json_loads(d.pop("related_claim_ids_json")) or []
    )
    return d


def _assumption_row_to_dict(row: sqlite3.Row) -> dict:
    """Map a research_assumptions row to a dict with JSON columns parsed."""
    d = dict(row)
    d["context_tags"] = _json_loads(d.pop("context_tags_json")) or {}
    d["supporting_artifact_refs"] = _json_loads(
        d.pop("supporting_artifact_refs_json")) or []
    return d


# ── ClaimAssumption Repository (IDR-026: P7 write path, v6 §29) ──

class ResearchClaimError(Exception):
    """A claim/assumption write violates the approved advisory contract.

    Only an ADMITTED extraction result has a write path; supersession must
    reference the project's current head and must change content; the
    dereference resolver must accept every DEREFERENCE_DIMENSIONS tag; and
    nothing is ever updated or deleted (IDR-026 Decision 2).
    """


class ResearchClaimIntegrityError(ResearchClaimError):
    """A caller-claimed ADMITTED extraction whose identity is self-inconsistent.

    Raised at the persistence boundary when a claim/assumption's content
    identity (``claim_id``/``assumption_id``/``content_hash``) or schema
    version does not match the canonical derivation shared with the
    ClaimAssumptionValidator (EC-V6 discipline, IDR-026 Decision 2).
    Fail-closed: nothing is written, no links, no edges.
    """


class ExtractionTaskBindingError(ResearchClaimError):
    """An extraction write is refused because its producing task does not
    satisfy the task-output acceptance contract (V6-P7-A2-01/02/03).

    The producing task must exist, belong to the write's project, be an
    EXTRACT task, be RUNNING (re-checked inside the write transaction, so it
    is atomic with the write), and its ``spec.source_ref`` must equal the
    extraction's source. A task that already produced a *different* output is
    refused (one-shot acceptance; identical re-acceptance stays idempotent).
    Fail-closed: nothing is written.
    """


def _is_extract_spec(spec: Any) -> bool:
    """True iff ``spec`` carries the canonical EXTRACT template marker.

    Normalized (strip + casefold) against the canonical ``EXTRACT_TEMPLATE``
    constant — the same comparison the gateway applies at admission
    (V6-P7-E01), so admission and the write path never disagree.
    """
    if not isinstance(spec, dict):
        return False
    template = spec.get("template")
    return isinstance(template, str) and (
        template.strip().casefold() == EXTRACT_TEMPLATE)


class ClaimAssumptionRepository:
    """Read/write the immutable advisory ``ResearchClaim``/``ResearchAssumption``
    artifacts (v6 §29, IDR-026 — P7 write path).

    The write path is task-output acceptance: the extraction task proposes a
    schema'd output, ``validate_extraction`` decides admissibility
    (deterministic), and on ADMITTED this repository persists it atomically
    with its §14 provenance edges. No new event type is emitted (IDR-026
    Decision 4); the audit is the immutable rows + edges + the producing
    task's existing events. Defenses-in-depth, in order:

    1. Only ``ADMITTED`` results are accepted — there is no write path for an
       unvalidated extraction (IDR-026 Decision 2.1).
    2. Identity is re-derived with the SAME pure helpers the validator uses
       (``claim_id_of``/``assumption_id_of``) — a forged id or content_hash
       fails closed with 0 rows, 0 links, 0 edges (EC-V6 discipline).
    3. The dereference resolver is constructed here over the real
       authoritative carriers: ``dataset_ref`` must resolve to a
       ``dataset_manifests`` row in the intent's project; ``regime``/
       ``methodology`` are form-checked only (their axis stores are
       DEFERRED — IDR-026 Decision 3, documented boundary, never a bypass).
    4. Idempotency: per-artifact ``UNIQUE (project_id, content_hash)`` — a
       duplicate returns the existing row; a supersession with unchanged
       content fails loudly (E9 analog: a new version changes the content).
    5. Supersession is head-only: the target must exist, be project-scoped,
       and not already be superseded; a superseded assumption flips to
       ``SUPERSEDED`` deterministically (CT-R4's one deterministic case).
    6. No UPDATE/DELETE path exists at all — immutability is structural.
    """

    def __init__(self, conn: sqlite3.Connection, clock: Clock | None = None):
        self._conn = conn
        self._clock = clock or utc_now

    # ── the write path ──

    def _make_resolver(self, project_id: str) -> ContextResolver:
        """The real dereference resolver over authoritative carriers.

        ``dataset_ref`` → a ``dataset_manifests`` row in the intent's project
        (cross-project dereference rejected). ``regime`` resolves against the
        closed regime registry (Step 4 / S-R2 wiring, IDR-044): a declared
        regime context tag dereferences iff it is a registry-registered
        versioned tag (bare IDs and unregistered pairs reject — the store
        is no longer a DEFERRED phase). ``methodology`` remains
        form-checked: its store (ExperimentSpec) is a DEFERRED phase —
        documented boundary, not a bypass (IDR-026 Decision 3).
        """
        def resolve(dimension: str, value: str) -> bool:
            if dimension == "dataset_ref":
                row = self._conn.execute(
                    "SELECT 1 FROM dataset_manifests "
                    "WHERE manifest_id = ? AND project_id = ?",
                    (value, project_id),
                ).fetchone()
                return row is not None
            if dimension == "regime":
                try:
                    resolve_regime(parse_regime_ref(value))
                except (RegimeResolutionError, TypeError):
                    return False
                return True
            return True  # deferred dimensions: form-checked only
        return resolve

    def _dereference_artifact_ref(self, project_id: str, ref: str) -> bool:
        """Dereference an 'artifact_type:ref' against existing carriers.

        V6-P7-F02: the substrate contract dereferences ``source_ref`` /
        supporting artifact refs at the write path. The vocabulary is CLOSED
        (F1 audit generalization): every artifact type is explicitly decided
        — resolved against a real carrier, documented as a deferred carrier
        (form-checked only, no store yet), or refused. Unknown types fail
        closed: a type with no explicit decision never passes silently.
        """
        if REF_SEP not in ref:
            return False  # never trust a bare id (form-checked upstream)
        artifact_type, _, artifact_id = ref.partition(REF_SEP)
        if artifact_type == "dataset_manifest":
            row = self._conn.execute(
                "SELECT 1 FROM dataset_manifests "
                "WHERE manifest_id = ? AND project_id = ?",
                (artifact_id, project_id),
            ).fetchone()
            return row is not None
        if artifact_type in ("source_result", "source_payload"):
            # SD-05 — this step lands the source artifact types against the
            # `artifacts` table (FULL content-hash key, project-edge-scoped):
            # a missing ref now FAILS instead of the form-checked pass.
            # S6-A1 — the ref prefix is the artifact type; a `source_result:`
            # ref never dereferences a `source_payload` row (or vice versa).
            return _source_artifact_resolves(
                self._conn, project_id, artifact_id, artifact_type)
        if artifact_type == "failure_classification":
            # IDR-037 D8 (advisory boundary, audit finding): a failure
            # classification is advisory metadata, never a source document —
            # no resolver outside the Q-05 slice may dereference it, and no
            # deferred-carrier form-check may let a claim/assumption
            # nominally cite one as its source_ref.
            return False
        # Documented deferred carriers (task-output context, e.g. the
        # extraction batch source): no store exists yet, so they are
        # accepted form-checked ONLY — an explicit decision, never a
        # silent pass. The resolver is the extension point when the
        # store lands. F1 audit closure: unknown / unsupported artifact
        # types fail closed — the vocabulary is closed, a type with no
        # explicit decision (real resolver, documented deferral, or D8
        # refusal) is refused, never a form-checked pass. External
        # identifiers (doi:, arxiv:, pmid:), generic catch-alls
        # (artifact:, source:), and non-source carriers (model_ref:,
        # validation:, research_program:) have no carrier on this path
        # and must not be silently accepted.
        return artifact_type in DEFERRED_ARTIFACT_CARRIERS

    def record_extraction(
        self,
        project_id: str,
        result: ExtractionResult,
        *,
        producing_task_id: str,
        extracted_by: str = "extraction_task",
        reason: str = "",
    ) -> dict:
        """Persist an ADMITTED extraction atomically with links and edges,
        bound to its producing task (V6-P7-A2-01/02/03).

        ``producing_task_id`` is required and verified INSIDE the write
        transaction (atomic with the write): the task must exist, belong to
        ``project_id``, be an EXTRACT task, be RUNNING, and its
        ``spec.source_ref`` must equal ``result.source_ref``. One-shot
        acceptance: a task that already produced a *different* output is
        refused (identical re-acceptance stays idempotent). The task id is
        persisted on every row (migration 5→6).

        Raises ``ExtractionTaskBindingError`` for a task-binding violation,
        ``ResearchClaimError`` for any other contract violation, and
        ``ResearchClaimIntegrityError`` when a caller-claimed artifact's
        identity does not match the canonical derivation (fail-closed —
        nothing written). Returns a summary dict with the persisted
        claim/assumption rows, links, and edges.
        """
        if not result.admitted:
            reasons = [
                f"{e.code}@{e.field_path}: {e.explanation}"
                for e in result.errors
            ]
            raise ResearchClaimError(
                f"refusing to persist a non-ADMITTED extraction "
                f"(verdict={result.verdict.value}) — no write path for "
                f"unvalidated extractions (IDR-026): {'; '.join(reasons)}"
            )
        if not result.claims and not result.assumptions:
            raise ResearchClaimError(
                "refusing to persist an empty extraction — ADMITTED requires "
                "at least one claim or assumption"
            )
        # claim-ground (G13): provenance is advisory and read from the
        # validated result; absent provenance stays None (unknown).
        provenance_model_ref = result.model_ref
        provenance_prompt_template_version = result.prompt_template_version
        provenance_run_id = result.run_id
        # 0b. Governance: the project must exist (V6-P7-F03). Resolved here,
        #    never trusted from the caller — a nonexistent project must fail
        #    with a structured error, not a raw FK IntegrityError.
        proj = self._conn.execute(
            "SELECT 1 FROM projects WHERE project_id = ?",
            (project_id,),
        ).fetchone()
        if proj is None:
            raise ResearchClaimError(
                f"Project not found: {project_id!r} — claims/assumptions are "
                f"project-scoped artifacts (IDR-026)"
            )

        # 2. Integrity boundary (EC-V6 discipline): re-derive identity with
        #    the same helpers; any mismatch fails closed before the write.
        for c in result.claims:
            expected = claim_id_of(
                c.statement, c.source_ref, c.span_ref, c.claim_type,
                dict(c.context_tags), c.support_state, c.related_claim_ids)
            if c.claim_id != expected or c.content_hash != expected:
                raise ResearchClaimIntegrityError(
                    f"claim_id/content_hash {c.claim_id!r} does not match the "
                    f"canonical content identity {expected!r} — identity is "
                    f"derived, never authored (IDR-026)"
                )
            if c.schema_version != CLAIM_SCHEMA_VERSION:
                raise ResearchClaimIntegrityError(
                    f"schema_version {c.schema_version!r} is not the "
                    f"implemented schema {CLAIM_SCHEMA_VERSION!r} (IDR-026)"
                )
            # assumption_ids must resolve to this batch (substrate rule 5)
            batch_aids = {a.assumption_id for a in result.assumptions}
            dangling = [aid for aid in c.assumption_ids
                        if aid not in batch_aids]
            if dangling:
                raise ResearchClaimIntegrityError(
                    f"claim {c.claim_id!r} references assumption ids outside "
                    f"the batch: {dangling} — links are batch-resolved by "
                    f"the validator (IDR-026)"
                )
        for a in result.assumptions:
            expected = assumption_id_of(
                a.statement, dict(a.context_tags), a.supporting_artifact_refs)
            if a.assumption_id != expected or a.content_hash != expected:
                raise ResearchClaimIntegrityError(
                    f"assumption_id/content_hash {a.assumption_id!r} does not "
                    f"match the canonical content identity {expected!r} — "
                    f"identity is derived, never authored (IDR-026)"
                )
            if a.schema_version != CLAIM_SCHEMA_VERSION:
                raise ResearchClaimIntegrityError(
                    f"schema_version {a.schema_version!r} is not the "
                    f"implemented schema {CLAIM_SCHEMA_VERSION!r} (IDR-026)"
                )

        # 3. Dereference gate (real resolver, project-scoped). Context tags
        #    (V6-P7-F02) AND the artifact refs (source_ref / supporting
        #    artifact refs) must dereference against existing authoritative
        #    carriers — the substrate contract says source_ref is dereferenced
        #    at the write path (claims.py).
        resolver = self._make_resolver(project_id)
        for c in result.claims:
            for dim, value in c.context_tags:
                if dim in DEREFERENCE_DIMENSIONS and not resolver(dim, value):
                    raise ResearchClaimError(
                        f"dangling context ref {dim}:{value!r} on claim "
                        f"{c.claim_id!r} — authoritative carriers must "
                        f"dereference in project {project_id!r} (IDR-026)"
                    )
            if not self._dereference_artifact_ref(project_id, c.source_ref):
                raise ResearchClaimError(
                    f"dangling source_ref {c.source_ref!r} on claim "
                    f"{c.claim_id!r} — the cited artifact must dereference in "
                    f"project {project_id!r} (IDR-026)"
                )
        for a in result.assumptions:
            for r in a.supporting_artifact_refs:
                if not self._dereference_artifact_ref(project_id, r):
                    raise ResearchClaimError(
                        f"dangling supporting artifact ref {r!r} on assumption "
                        f"{a.assumption_id!r} — the cited artifact must "
                        f"dereference in project {project_id!r} (IDR-026)"
                    )

        ts = self._clock()
        self._conn.execute("BEGIN IMMEDIATE")
        try:
            # 3b. Task binding — verified INSIDE the transaction so the
            #     status read is atomic with the write (V6-P7-A2-02 TOCTOU
            #     closure): any concurrent transition_status commits before
            #     or after this transaction, never between check and write.
            task = self._conn.execute(
                "SELECT * FROM tasks WHERE task_id = ?",
                (producing_task_id,),
            ).fetchone()
            if task is None:
                raise ExtractionTaskBindingError(
                    f"extraction write refused: producing task "
                    f"{producing_task_id!r} does not exist (V6-P7-A2-01) — "
                    f"claims are task output and require a producing task"
                )
            if task["project_id"] != project_id:
                raise ExtractionTaskBindingError(
                    f"extraction write refused: producing task "
                    f"{producing_task_id!r} belongs to project "
                    f"{task['project_id']!r}, not {project_id!r} (V6-P7-A2-01)"
                )
            task_spec = _json_loads(task["spec_json"]) or {}
            if not _is_extract_spec(task_spec):
                raise ExtractionTaskBindingError(
                    f"extraction write refused: producing task "
                    f"{producing_task_id!r} is not an EXTRACT task "
                    f"(spec.template != {EXTRACT_TEMPLATE!r}) (V6-P7-A2-01)"
                )
            if task["status"] != TaskStatus.RUNNING.value:
                raise ExtractionTaskBindingError(
                    f"extraction write refused: producing task "
                    f"{producing_task_id!r} is {task['status']}, not RUNNING "
                    f"(V6-P7-A2-02) — output may only be accepted from a task "
                    f"currently executing"
                )
            task_source = task_spec.get("source_ref")
            if task_source != result.source_ref:
                raise ExtractionTaskBindingError(
                    f"extraction write refused: extraction source "
                    f"{result.source_ref!r} does not match the producing "
                    f"task's spec.source_ref {task_source!r} (V6-P7-A2-01)"
                )
            # 3c. One-shot acceptance (V6-P7-A2-03): a task that already
            #     produced a *different* output is refused. Identical
            #     re-acceptance (crash/rerun) stays idempotent — the content
            #     hashes match, so the per-artifact UNIQUE collapse below
            #     reuses the existing rows.
            prior = self._conn.execute(
                "SELECT content_hash FROM research_claims "
                "WHERE producing_task_id = ?", (producing_task_id,),
            ).fetchall()
            if prior:
                proposed = {c.content_hash for c in result.claims}
                existing = {r["content_hash"] for r in prior}
                if existing != proposed:
                    raise ExtractionTaskBindingError(
                        f"extraction write refused: producing task "
                        f"{producing_task_id!r} already produced an output "
                        f"with different content — one execution, one output "
                        f"(V6-P7-A2-03); identical re-acceptance is "
                        f"idempotent, divergent output is not"
                    )

            # 4. Persist assumptions first (claims link to them), then claims,
            #    then links + §14 edges.
            persisted_assumptions: dict[str, dict] = {}
            persisted_claims: dict[str, dict] = {}
            links: list[tuple[str, str]] = []
            edges: list[tuple[str, str, str]] = []
            superseded_targets: list[tuple[str, str]] = []  # (table, id)

            for a in result.assumptions:
                existing = self._conn.execute(
                    "SELECT * FROM research_assumptions "
                    "WHERE project_id = ? AND content_hash = ?",
                    (project_id, a.content_hash),
                ).fetchone()
                if existing is not None:
                    if a.supersedes_ref is not None:
                        self._conn.execute("ROLLBACK")
                        raise ResearchClaimError(
                            "supersession must change content — the "
                            "proposed assumption is identical to an existing "
                            "one (idempotent duplicate; a new version changes "
                            "the content, IDR-026)"
                        )
                    persisted_assumptions[a.assumption_id] = \
                        _assumption_row_to_dict(existing)
                    continue
                self._validate_supersede_target(
                    "research_assumptions", "assumption_id", project_id,
                    a.supersedes_ref, a.content_hash)
                # V6-P7-F01: status is governance, never caller-supplied — an
                # admission always lands ACTIVE; SUPERSEDED is the repository's
                # own deterministic flip below, and SUSPENDED is deferred to the
                # human/Director decision path (CT-R4).
                self._conn.execute(
                    """INSERT INTO research_assumptions
                       (assumption_id, project_id, content_hash, statement,
                        context_tags_json, supporting_artifact_refs_json,
                        status, schema_version, reason, supersedes_id,
                        producing_task_id, created_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (a.assumption_id, project_id, a.content_hash, a.statement,
                     _json_dumps(dict(a.context_tags)),
                     _json_dumps(list(a.supporting_artifact_refs)),
                     "ACTIVE", a.schema_version, reason, a.supersedes_ref,
                     producing_task_id, ts),
                )
                persisted_assumptions[a.assumption_id] = {
                    "assumption_id": a.assumption_id,
                    "project_id": project_id,
                    "content_hash": a.content_hash,
                    "statement": a.statement,
                    "context_tags": dict(a.context_tags),
                    "supporting_artifact_refs": list(a.supporting_artifact_refs),
                    "status": "ACTIVE",
                    "schema_version": a.schema_version,
                    "reason": reason,
                    "supersedes_id": a.supersedes_ref,
                    "created_at": ts,
                }
                if a.supersedes_ref is not None:
                    edges.append((a.assumption_id, a.supersedes_ref, "supersedes"))
                    superseded_targets.append(("assumption", a.supersedes_ref))

            for c in result.claims:
                existing = self._conn.execute(
                    "SELECT * FROM research_claims "
                    "WHERE project_id = ? AND content_hash = ?",
                    (project_id, c.content_hash),
                ).fetchone()
                if existing is not None:
                    if c.supersedes_ref is not None:
                        self._conn.execute("ROLLBACK")
                        raise ResearchClaimError(
                            "supersession must change content — the proposed "
                            "claim is identical to an existing one "
                            "(idempotent duplicate; a new version changes the "
                            "content, IDR-026)"
                        )
                    persisted_claims[c.claim_id] = _claim_row_to_dict(existing)
                    continue
                self._validate_supersede_target(
                    "research_claims", "claim_id", project_id,
                    c.supersedes_ref, c.content_hash)
                self._conn.execute(
                    """INSERT INTO research_claims
                       (claim_id, project_id, content_hash, statement,
                        source_ref, support_state, span_ref, claim_type,
                        context_tags_json, schema_version, extracted_by,
                        reason, supersedes_id, producing_task_id,
                        related_claim_ids_json, created_at,
                        model_ref, prompt_template_version, run_id)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                               ?, ?, ?, ?, ?)""",
                    (c.claim_id, project_id, c.content_hash, c.statement,
                     c.source_ref, c.support_state, c.span_ref, c.claim_type,
                     _json_dumps(dict(c.context_tags)),
                     c.schema_version, extracted_by, reason, c.supersedes_ref,
                     producing_task_id, _json_dumps(list(c.related_claim_ids)),
                     ts,
                     # claim-ground G13: NULL = unknown (never fabricated).
                     provenance_model_ref, provenance_prompt_template_version,
                     provenance_run_id),
                )
                persisted_claims[c.claim_id] = {
                    "claim_id": c.claim_id,
                    "project_id": project_id,
                    "content_hash": c.content_hash,
                    "statement": c.statement,
                    "source_ref": c.source_ref,
                    "support_state": c.support_state,
                    "span_ref": c.span_ref,
                    "claim_type": c.claim_type,
                    "context_tags": dict(c.context_tags),
                    "related_claim_ids": list(c.related_claim_ids),
                    "schema_version": c.schema_version,
                    "extracted_by": extracted_by,
                    "reason": reason,
                    "supersedes_id": c.supersedes_ref,
                    "created_at": ts,
                }
                # §14 edges: derived_from source; cites assumptions
                edges.append((c.claim_id, c.source_ref, "derived_from"))
                for aid in c.assumption_ids:
                    links.append((c.claim_id, aid))
                    edges.append((c.claim_id, aid, "cites"))
                if c.supersedes_ref is not None:
                    edges.append((c.claim_id, c.supersedes_ref, "supersedes"))
                    superseded_targets.append(("claim", c.supersedes_ref))

            # 5. Write links + edges (UNIQUE constraints make reruns idempotent).
            for claim_id, assumption_id in links:
                self._conn.execute(
                    "INSERT OR IGNORE INTO claim_assumption_links "
                    "(claim_id, assumption_id) VALUES (?, ?)",
                    (claim_id, assumption_id),
                )
            for artifact_id, upstream_id, edge_type in edges:
                self._conn.execute(
                    "INSERT OR IGNORE INTO provenance_edges "
                    "(artifact_id, upstream_id, edge_type, created_at) "
                    "VALUES (?, ?, ?, ?)",
                    (artifact_id, upstream_id, edge_type, ts),
                )

            # 6. Deterministic CT-R4 transition: a superseded assumption
            #    flips to SUPERSEDED in the same transaction.
            for kind, target_id in superseded_targets:
                if kind == "assumption":
                    self._conn.execute(
                        "UPDATE research_assumptions SET status = 'SUPERSEDED' "
                        "WHERE assumption_id = ? AND project_id = ?",
                        (target_id, project_id),
                    )

            self._conn.execute("COMMIT")
        except ResearchClaimError:
            if self._conn.in_transaction:
                self._conn.execute("ROLLBACK")
            raise
        except Exception:
            if self._conn.in_transaction:
                self._conn.execute("ROLLBACK")
            raise

        return {
            "project_id": project_id,
            "verdict": ExtractionVerdict.ADMITTED.value,
            "claims": sorted(persisted_claims.values(), key=lambda d: d["claim_id"]),
            "assumptions": sorted(
                persisted_assumptions.values(), key=lambda d: d["assumption_id"]),
            "links": sorted(links),
            "edges": sorted(edges),
            "superseded": sorted(
                [tid for _, tid in superseded_targets]),
        }

    def _validate_supersede_target(
        self, table: str, id_col: str, project_id: str,
        supersedes_ref: str | None, content_hash: str,
    ) -> None:
        """Head-only supersession: target exists, project-scoped, not already
        superseded, and content differs (E9 analog)."""
        if supersedes_ref is None:
            return
        target = self._conn.execute(
            f"SELECT * FROM {table} WHERE {id_col} = ? AND project_id = ?",
            (supersedes_ref, project_id),
        ).fetchone()
        if target is None:
            self._conn.execute("ROLLBACK")
            raise ResearchClaimError(
                f"Supersede target not found: {supersedes_ref!r} in project "
                f"{project_id!r} (IDR-026)"
            )
        if target["content_hash"] == content_hash:
            self._conn.execute("ROLLBACK")
            raise ResearchClaimError(
                "supersession must change content — the superseding artifact "
                "is identical to its target (IDR-026)"
            )
        already = self._conn.execute(
            f"SELECT 1 FROM {table} WHERE supersedes_id = ? AND project_id = ?",
            (supersedes_ref, project_id),
        ).fetchone()
        if already is not None:
            self._conn.execute("ROLLBACK")
            raise ResearchClaimError(
                f"Supersede target {supersedes_ref!r} is not the current head "
                f"— new versions supersede the head only (IDR-026)"
            )

    # ── read side (no update, no delete — immutability is structural) ──

    def get_claim(self, claim_id: str) -> dict:
        row = self._conn.execute(
            "SELECT * FROM research_claims WHERE claim_id = ?",
            (claim_id,),
        ).fetchone()
        if row is None:
            raise NotFoundError(f"ResearchClaim not found: {claim_id}")
        return _claim_row_to_dict(row)

    def get_assumption(self, assumption_id: str) -> dict:
        row = self._conn.execute(
            "SELECT * FROM research_assumptions WHERE assumption_id = ?",
            (assumption_id,),
        ).fetchone()
        if row is None:
            raise NotFoundError(f"ResearchAssumption not found: {assumption_id}")
        return _assumption_row_to_dict(row)

    def claims_for_project(self, project_id: str) -> list[dict]:
        rows = self._conn.execute(
            "SELECT * FROM research_claims WHERE project_id = ? "
            "ORDER BY created_at, claim_id",
            (project_id,),
        ).fetchall()
        return [_claim_row_to_dict(r) for r in rows]

    def assumptions_for_project(self, project_id: str) -> list[dict]:
        rows = self._conn.execute(
            "SELECT * FROM research_assumptions WHERE project_id = ? "
            "ORDER BY created_at, assumption_id",
            (project_id,),
        ).fetchall()
        return [_assumption_row_to_dict(r) for r in rows]

    def claims_depending_on(self, assumption_id: str) -> list[dict]:
        """All claims that depend on an assumption (the link table query)."""
        rows = self._conn.execute(
            "SELECT c.* FROM research_claims c "
            "JOIN claim_assumption_links l ON l.claim_id = c.claim_id "
            "WHERE l.assumption_id = ? ORDER BY c.created_at, c.claim_id",
            (assumption_id,),
        ).fetchall()
        return [_claim_row_to_dict(r) for r in rows]

    def assumptions_of(self, claim_id: str) -> list[dict]:
        """All assumptions a claim depends on (the link table query)."""
        rows = self._conn.execute(
            "SELECT a.* FROM research_assumptions a "
            "JOIN claim_assumption_links l ON l.assumption_id = a.assumption_id "
            "WHERE l.claim_id = ? ORDER BY a.created_at, a.assumption_id",
            (claim_id,),
        ).fetchall()
        return [_assumption_row_to_dict(r) for r in rows]

    def head(self, claim_id: str) -> dict:
        """The head of the claim's supersession chain (follows supersedes)."""
        current_id = claim_id
        seen: set[str] = set()
        while current_id not in seen:
            seen.add(current_id)
            row = self._conn.execute(
                "SELECT * FROM research_claims WHERE claim_id = ?",
                (current_id,),
            ).fetchone()
            if row is None:
                raise NotFoundError(f"ResearchClaim not found: {current_id}")
            if row["supersedes_id"] is None:
                return _claim_row_to_dict(row)
            current_id = row["supersedes_id"]
        raise ResearchClaimError(
            f"supersession cycle detected through claim {claim_id!r}"
        )


class EmptyResultArtifactRepository:
    """Persist / resolve the S1 empty-result-set search records (AR-03,
    migration 6→7).

    A ``counter_search: {result: NONE_FOUND}`` in a thesis-evidence table is
    only certifiable if it references a persisted artifact: the query terms
    actually run + the provider response actually received. This repository
    is the write path for those records:

    - Content-addressed identity (``sr_<sha256>[:24]`` over query +
      response); a forged id or content hash fails closed (EC-V6
      discipline, same helpers as the validator).
    - ``UNIQUE (project_id, content_hash)`` idempotency (PA4 pattern) — a
      duplicate record returns the existing row.
    - Immutable, project-scoped, no UPDATE/DELETE path.
    - A search record, never evidence: it certifies that a search ran and
      came back empty; it cannot promote or refute a claim.
    """

    def __init__(self, conn: sqlite3.Connection, clock: Clock | None = None):
        self._conn = conn
        self._clock = clock or utc_now

    def record(self, project_id: str, query_terms: Sequence[str],
               provider_response: str) -> dict:
        """Persist an empty-result search record atomically (idempotent).

        Identity is content-derived with the validator's own helpers — a
        caller-supplied ``artifact_id`` is never trusted. Returns the
        persisted row (existing row for a duplicate).
        """
        from hermes.research.thesis import (
            empty_result_content_hash_of,
            empty_result_id_of,
        )

        if not query_terms:
            raise ResearchClaimError(
                "refusing to persist an empty-result artifact with no query "
                "terms — the record must say what was searched (AR-03)"
            )
        if not provider_response or not isinstance(provider_response, str):
            raise ResearchClaimError(
                "refusing to persist an empty-result artifact without a "
                "provider response (AR-03)"
            )
        content_hash = empty_result_content_hash_of(query_terms,
                                                    provider_response)
        artifact_id = empty_result_id_of(query_terms, provider_response)

        existing = self._conn.execute(
            "SELECT * FROM empty_result_artifacts "
            "WHERE project_id = ? AND content_hash = ?",
            (project_id, content_hash),
        ).fetchone()
        if existing is not None:
            return dict(existing)

        ts = self._clock()
        self._conn.execute("BEGIN IMMEDIATE")
        try:
            self._conn.execute(
                """INSERT INTO empty_result_artifacts
                   (artifact_id, project_id, content_hash, query_terms_json,
                    provider_response_json, created_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (artifact_id, project_id, content_hash,
                 _json_dumps(sorted(query_terms)), provider_response, ts),
            )
            self._conn.execute("COMMIT")
        except Exception:
            if self._conn.in_transaction:
                self._conn.execute("ROLLBACK")
            raise
        return self.get(artifact_id)

    def get(self, artifact_id: str) -> dict:
        """The persisted artifact (parsed columns)."""
        row = self._conn.execute(
            "SELECT * FROM empty_result_artifacts "
            "WHERE artifact_id = ?", (artifact_id,),
        ).fetchone()
        if row is None:
            raise NotFoundError(
                f"EmptyResultArtifact not found: {artifact_id}")
        return {
            "artifact_id": row["artifact_id"],
            "project_id": row["project_id"],
            "content_hash": row["content_hash"],
            "query_terms": _json_loads(row["query_terms_json"]) or [],
            "provider_response": row["provider_response_json"],
            "created_at": row["created_at"],
        }

    def resolver(self) -> EmptyResultResolver:
        """The write-path resolver the validator consumes: artifact_id →
        persisted artifact (None when missing)."""
        def resolve(project_id: str, artifact_id: str) -> dict | None:
            try:
                artifact = self.get(artifact_id)
            except NotFoundError:
                return None
            if artifact["project_id"] != project_id:
                return None
            return artifact
        return resolve


class CuratedKnowledgeRepository:
    """READ-ONLY consumption surface for the Step 7 curated knowledge registry
    (v6 §16.6, migration 14→15).

    The registry is journally-derived: the admission transaction (gateway
    ``_validate_curate_knowledge``) is the ONE write path; this repository
    only ANSWERS project-scoped reads. Advisory-only (D8 discipline): a
    curated entry is a reference index for the S7 near-miss screen — never
    evidence, never an authority over the ladder or the journal.

    Read contract (charter §15):

    - project-scoped (``source_project_id = project_id`` on every query);
    - the ACTIVE set excludes SUPERSEDED and INVALIDATED entries;
    - deterministic ordering (``curated_id ASC``);
    - the S7 result shape omits ``source_project_id``, the binding's
      artifact content, and ``admission_event_ref`` (no unrelated
      project/artifact/admission-event data leaks through the screen);
    - never writes: no INSERT/UPDATE/DELETE path exists here.
    """

    def __init__(self, conn: sqlite3.Connection):
        self._conn = conn

    # ── row shaping ──

    @staticmethod
    def _entry_row(row: Any, *, include_provenance: bool) -> dict:
        """One registry row as a dict. The S7 screen shape
        (``include_provenance=False``) omits source_project_id,
        admission_event_ref, and the binding ref — the audit shape carries
        them (project-scoped callers only)."""
        d = {
            "curated_id": row["curated_id"],
            "kind": row["kind"],
            "signature_json": row["signature_json"],
            "program_ref": row["program_ref"],
            "hypothesis_ref": row["hypothesis_ref"],
            "status": row["status"],
            "admitted_at": row["admitted_at"],
        }
        if include_provenance:
            d["source_project_id"] = row["source_project_id"]
            d["source_binding_ref"] = row["source_binding_ref"]
            d["source_decision_event_ref"] = row["source_decision_event_ref"]
            d["admission_event_ref"] = row["admission_event_ref"]
            d["admission_decision_ref"] = row["admission_decision_ref"]
            d["invalidation_event_ref"] = row["invalidation_event_ref"]
        return d

    # ── reads ──

    def active_entries(self, project_id: str) -> list[dict]:
        """The project's ADMITTED entries (the active S7 set), curated_id
        ASC, screen shape (no provenance columns)."""
        rows = self._conn.execute(
            "SELECT * FROM curated_knowledge_entries "
            "WHERE source_project_id = ? AND status = 'ADMITTED' "
            "ORDER BY curated_id ASC",
            (project_id,),
        ).fetchall()
        return [self._entry_row(r, include_provenance=False) for r in rows]

    def screen_matches(self, project_id: str, signature_json: str,
                       ) -> list[dict]:
        """The S7 near-miss screen (charter §15): the project's ADMITTED
        entries whose signature EXACTLY equals ``signature_json`` — no
        fuzzy/semantic matching. Deterministic (curated_id ASC), screen
        shape."""
        rows = self._conn.execute(
            "SELECT * FROM curated_knowledge_entries "
            "WHERE source_project_id = ? AND status = 'ADMITTED' "
            "  AND signature_json = ? "
            "ORDER BY curated_id ASC",
            (project_id, signature_json),
        ).fetchall()
        return [self._entry_row(r, include_provenance=False) for r in rows]

    def entry(self, project_id: str, curated_id: str) -> dict | None:
        """One entry with full provenance (audit shape), or None when it is
        not in this project (project isolation — a foreign curated_id never
        resolves)."""
        row = self._conn.execute(
            "SELECT * FROM curated_knowledge_entries "
            "WHERE source_project_id = ? AND curated_id = ?",
            (project_id, curated_id),
        ).fetchone()
        if row is None:
            return None
        return self._entry_row(row, include_provenance=True)

    def all_entries(self, project_id: str) -> list[dict]:
        """Every entry in the project regardless of status (the audit
        surface), curated_id ASC, full provenance shape."""
        rows = self._conn.execute(
            "SELECT * FROM curated_knowledge_entries "
            "WHERE source_project_id = ? ORDER BY curated_id ASC",
            (project_id,),
        ).fetchall()
        return [self._entry_row(r, include_provenance=True) for r in rows]

    def basis(self, project_id: str, curated_id: str) -> list[str]:
        """The entry's immutable retraction-basis set — sorted bare
        evidence artifact_ids (charter §4). Empty list when the entry is
        not in this project (project isolation)."""
        rows = self._conn.execute(
            "SELECT b.evidence_artifact_id "
            "FROM curated_knowledge_retraction_basis b "
            "JOIN curated_knowledge_entries e "
            "  ON e.curated_id = b.curated_id "
            "WHERE e.source_project_id = ? AND b.curated_id = ? "
            "ORDER BY b.evidence_artifact_id ASC",
            (project_id, curated_id),
        ).fetchall()
        return [r["evidence_artifact_id"] for r in rows]

    def supersession(self, project_id: str, curated_id: str,
                     ) -> dict | None:
        """The supersession row naming ``curated_id`` as the successor (the
        entry that superseded another), or None. Project-scoped via the
        successor's registry row."""
        row = self._conn.execute(
            "SELECT s.new_curated_id, s.supersedes_ref, "
            "       s.supersession_event_ref "
            "FROM curated_knowledge_supersession s "
            "JOIN curated_knowledge_entries e "
            "  ON e.curated_id = s.new_curated_id "
            "WHERE e.source_project_id = ? AND s.new_curated_id = ?",
            (project_id, curated_id),
        ).fetchone()
        if row is None:
            return None
        return {
            "new_curated_id": row["new_curated_id"],
            "supersedes_ref": row["supersedes_ref"],
            "supersession_event_ref": row["supersession_event_ref"],
        }


class ContradictionRepository:
    """Read-only contradiction surfaces (CHG-1).

    All writes happen inside gateway admission transactions; this class
    only reads. Every method is project-scoped and deterministic
    (``contradiction_id ASC``).
    """

    def __init__(self, conn: Any) -> None:
        self._conn = conn

    @staticmethod
    def _row(row: Any) -> dict:
        import json as _json
        try:
            overlap = _json.loads(row["evidence_overlap_json"] or "[]")
        except ValueError:
            overlap = []
        if not isinstance(overlap, list):
            overlap = []
        return {
            "contradiction_id": row["contradiction_id"],
            "project_id": row["project_id"],
            "type": row["type"],
            "party_a": row["party_a"],
            "party_b": row["party_b"],
            "evidence_overlap": overlap,
            "status": row["status"],
            "detector_version": row["detector_version"],
            "detected_at": row["detected_at"],
            "detection_event_ref": row["detection_event_ref"],
            "resolution_event_ref": row["resolution_event_ref"],
            "resolution_rationale_digest": row[
                "resolution_rationale_digest"],
            "supersedes_ref": row["supersedes_ref"],
            "created_at": row["created_at"],
        }

    @staticmethod
    def _party_active(conn: Any, artifact_id: str) -> bool:
        """A party is active iff its artifact row exists and carries no
        invalidation marker (fail-closed: missing/corrupt rows count as
        inactive — the lazy half of the active rule)."""
        import json as _json
        row = conn.execute(
            "SELECT metadata_json FROM artifacts WHERE artifact_id = ?",
            (artifact_id,)).fetchone()
        if row is None:
            return False
        try:
            meta = _json.loads(row["metadata_json"]) if (
                row["metadata_json"]) else {}
        except ValueError:
            return False
        if not isinstance(meta, dict):
            return False
        return meta.get("invalidation_marker") != "INVALIDATED"

    def open_contradictions(self, project_id: str) -> list[dict]:
        """Operationally active contradictions: OPEN rows whose parties
        remain valid (no invalidation marker). Deterministic
        (contradiction_id ASC). The lazy half of the active rule — the
        S5 follow-on retires rows eagerly in-transaction."""
        rows = self._conn.execute(
            "SELECT * FROM contradictions "
            "WHERE project_id = ? AND status = 'OPEN' "
            "ORDER BY contradiction_id ASC",
            (project_id,),
        ).fetchall()
        out = []
        for row in rows:
            if not self._party_active(self._conn, row["party_a"]):
                continue
            if not self._party_active(self._conn, row["party_b"]):
                continue
            out.append(self._row(row))
        return out

    def entry(self, project_id: str, contradiction_id: str) -> dict | None:
        """One contradiction row with full provenance, or None when it is
        not in this project (project isolation)."""
        row = self._conn.execute(
            "SELECT * FROM contradictions "
            "WHERE project_id = ? AND contradiction_id = ?",
            (project_id, contradiction_id),
        ).fetchone()
        if row is None:
            return None
        return self._row(row)

    def all_entries(self, project_id: str) -> list[dict]:
        """Every contradiction row in the project regardless of status
        (the audit surface), contradiction_id ASC."""
        rows = self._conn.execute(
            "SELECT * FROM contradictions WHERE project_id = ? "
            "ORDER BY contradiction_id ASC",
            (project_id,),
        ).fetchall()
        return [self._row(r) for r in rows]
