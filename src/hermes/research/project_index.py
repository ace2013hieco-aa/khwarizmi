"""The OPS-18 project-index adapter — rows plus chain nodes to entries.

The durable rows come from :mod:`hermes.persistence.project_index` (three
project-scoped ``SELECT``s and three ``COUNT``s). The chain nodes come from the
run's in-memory ``SubstrateStore``; they are never queried from a database and
a fresh process has none. This module is the one place labels, ordering and the
40-entry cap are applied.

It is a read-side adapter: no transaction, no writer, no authority. It imports
the persistence projection and the runtime's pure envelope types, and it is
injected into the methodology driver as a callable so the handler package
keeps its "never persistence" import discipline.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from hermes.agents.runtime.assembly import (
    PROJECT_INDEX_MAX_ENTRIES,
    ProjectIndexChainNode,
    ProjectIndexEntry,
    ProjectIndexView,
)
from hermes.persistence.project_index import read_project_index_rows

__all__ = ["INDEX_ROW_LIMIT", "ProjectIndexReader"]

#: One row beyond the entry cap is enough to fill the index from any one
#: category while the exact counts still make ``omitted`` truthful.
INDEX_ROW_LIMIT = PROJECT_INDEX_MAX_ENTRIES + 1


def _task_entry(task_id: str, task_type: str, status: str) -> ProjectIndexEntry:
    return ProjectIndexEntry(
        id=task_id, kind="task", label=f"{status} {task_type}")


def _brief_entry(brief_id: str, version: int) -> ProjectIndexEntry:
    return ProjectIndexEntry(id=brief_id, kind="scope_brief", label=f"v{version}")


def _artifact_entry(artifact_id: str, artifact_type: str) -> ProjectIndexEntry:
    return ProjectIndexEntry(
        id=f"{artifact_type}:{artifact_id}", kind="artifact",
        label=artifact_type)


def _chain_entry(node: ProjectIndexChainNode) -> ProjectIndexEntry:
    # "not a task id" is deliberate: the gateway's dependency check is against
    # durable tasks, and an mnode_ id is in-memory derived state (B-5).
    return ProjectIndexEntry(
        id=node.node_id, kind="chain_node",
        label=f"{node.kind} chain node (not a task id)")


class ProjectIndexReader:
    """Read one project's bounded index — the composition-injected callable.

    The adapter is constructed with the controller's connection and called once
    per stage. It never writes and never starts a transaction: the durable half
    is three ``SELECT``s and three ``COUNT``s, and the chain half is the list
    the driver already holds.
    """

    def __init__(self, conn: Any) -> None:
        self._conn = conn

    def __call__(
        self, project_id: str,
        chain_nodes: Sequence[ProjectIndexChainNode] = (),
    ) -> ProjectIndexView:
        rows = read_project_index_rows(
            self._conn, project_id, limit=INDEX_ROW_LIMIT)

        entries: list[ProjectIndexEntry] = []
        # Priority order is the truncation priority: tasks, scope briefs,
        # artifacts, chain nodes. The tail is dropped first.
        entries.extend(
            _task_entry(task_id, task_type, status)
            for task_id, task_type, status in rows.tasks)
        entries.extend(
            _brief_entry(brief_id, version)
            for brief_id, version in rows.scope_briefs)
        entries.extend(
            _artifact_entry(artifact_id, artifact_type)
            for artifact_id, artifact_type in rows.artifacts)

        # Re-check the project bound even though the driver filters its store:
        # a foreign node must never enter another project's index.
        project_nodes = sorted(
            (node for node in chain_nodes if node.project_id == project_id),
            key=lambda node: node.node_id)
        entries.extend(_chain_entry(node) for node in project_nodes)

        total = (rows.task_total + rows.scope_brief_total
                 + rows.artifact_total + len(project_nodes))
        return ProjectIndexView(
            entries=tuple(entries[:PROJECT_INDEX_MAX_ENTRIES]),
            total=total)
