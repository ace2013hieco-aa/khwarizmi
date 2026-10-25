"""Read-only project index rows — the durable half of the OPS-18 read port.

What this module is, and is not
--------------------------------
It is a **read-only projection**: three bounded ``SELECT``s and three
``COUNT(*)``s, every one project-scoped, returning only the columns an index
entry needs. It opens no transaction, calls no ``BEGIN``/``COMMIT``/``ROLLBACK``,
and has no writer import. It is not a repository: it never creates, mutates or
journals anything.

The other half of the index — the methodology chain nodes — is **not here**.
``SubstrateStore.nodes`` is an in-memory dict (``methodology/substrate.py``),
so those entries come from the run's store object, not SQL. A fresh process
therefore sees none; that is the B-5 working-state rule, not a missing read.

Import discipline: stdlib only. No ``hermes.research`` import, no model or
capability port. The caller supplies the connection and the project id.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

__all__ = [
    "ProjectIndexRows",
    "read_project_index_rows",
]


@dataclass(frozen=True, slots=True)
class ProjectIndexRows:
    """The durable rows one project index may carry, plus their true totals.

    ``tasks`` is ``(task_id, task_type, status)``; ``artifacts`` is
    ``(artifact_id, artifact_type)``; ``scope_briefs`` is ``(brief_id,
    version)``. Each tuple is capped by the caller's ``limit``; the totals are
    the exact ``COUNT(*)`` values, which is what makes an ``omitted`` marker
    honest even when the read was bounded.
    """

    tasks: tuple[tuple[str, str, str], ...]
    artifacts: tuple[tuple[str, str], ...]
    scope_briefs: tuple[tuple[str, int], ...]
    task_total: int
    artifact_total: int
    scope_brief_total: int


def _count(conn: Any, table: str, project_id: str) -> int:
    row = conn.execute(
        f"SELECT COUNT(*) FROM {table} WHERE project_id = ?",
        (project_id,)).fetchone()
    return int(row[0])


def read_project_index_rows(
    conn: Any, project_id: str, *, limit: int = 41,
) -> ProjectIndexRows:
    """Read the bounded durable rows for one project.

    Every statement binds ``project_id = ?``. ``limit`` bounds each table's
    fetched rows; because the caller's entry cap is no larger than the number
    of rows needed from any one table, ``limit = cap + 1`` is enough to fill
    the index while still knowing the exact totals from the counts.

    The statements are plain ``SELECT``/``COUNT`` calls on an autocommit
    connection: no transaction-control statement is issued, so the caller's
    transaction census cannot move.
    """
    if not str(project_id):
        raise ValueError("a project index read needs a non-empty project id")
    if limit < 0:
        raise ValueError("a project index read limit cannot be negative")

    task_rows = conn.execute(
        "SELECT task_id, task_type, status FROM tasks "
        "WHERE project_id = ? ORDER BY task_id LIMIT ?",
        (project_id, limit)).fetchall()
    artifact_rows = conn.execute(
        "SELECT artifact_id, artifact_type FROM artifacts "
        "WHERE project_id = ? ORDER BY artifact_id LIMIT ?",
        (project_id, limit)).fetchall()
    brief_rows = conn.execute(
        "SELECT brief_id, version FROM scope_briefs "
        "WHERE project_id = ? ORDER BY brief_id LIMIT ?",
        (project_id, limit)).fetchall()

    return ProjectIndexRows(
        tasks=tuple((str(row[0]), str(row[1]), str(row[2]))
                    for row in task_rows),
        artifacts=tuple((str(row[0]), str(row[1])) for row in artifact_rows),
        scope_briefs=tuple((str(row[0]), int(row[1])) for row in brief_rows),
        task_total=_count(conn, "tasks", project_id),
        artifact_total=_count(conn, "artifacts", project_id),
        scope_brief_total=_count(conn, "scope_briefs", project_id),
    )
