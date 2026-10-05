"""Task node contract (v4 §7) — persisted DAG node record.

The node contract is the full execution record for a task in the graph.
Nodes are created only by the controller templates or validated
INSERT_TASK/BRANCH intents — nothing appears in the graph without passing
the intent gateway (v3 §7). The repository maps between ``NodeContract``
and the ``tasks`` table (IDR-007).

INVALIDATED semantics (v4 §7 rule 4): an invalidated result stays archived
under its original hash — never deleted, never overwritten. A new node is
created for the re-run.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from hermes.core.task_status import TaskStatus


class NodeType(str, Enum):
    """v4 §7 node types."""

    AGENT_TASK = "AGENT_TASK"       # judgment via Agent Runtime
    TOOL_TASK = "TOOL_TASK"         # deterministic via Tool Runtime
    GATE = "GATE"                   # deterministic gate evaluation
    HUMAN_GATE = "HUMAN_GATE"       # stops on AWAITING_HUMAN
    SUBGRAPH = "SUBGRAPH"           # nested cluster (e.g. one experiment's pipeline)


class AgentProfile(str, Enum):
    """v4 §13 four-role profiles + DETERMINISTIC."""

    DIRECTOR = "DIRECTOR"
    RESEARCHER = "RESEARCHER"
    IMPLEMENTER = "IMPLEMENTER"
    ADVERSARY = "ADVERSARY"
    DETERMINISTIC = "DETERMINISTIC"


@dataclass(frozen=True, slots=True)
class NodeContract:
    """v4 §7 node contract.

    The persisted record is the authority. The repository converts between
    this domain object and the ``tasks`` table. Callers never set `status`
    directly — transitions go through the repository's transition methods,
    which call ``validate_task_transition()`` inside a transaction.

    F-11: Added missing fields from v4 §7: timeout, heartbeat_interval,
    retry_policy, permissions, and S13 skip-rate fields.
    """

    task_id: str
    project_id: str
    task_type: str                       # NodeType value
    idempotency_key: str                 # SHA-256 of spec + inputs
    attempt: int = 1
    status: str = TaskStatus.PENDING.value
    profile: str | None = None           # AgentProfile value (nullable for non-agent)
    iteration: int = 1                   # research iteration (v4 §7 "loops are re-instantiation")
    parent_task_id: str | None = None    # for SUBGRAPH nodes
    spec: dict[str, Any] = field(default_factory=dict)
    inputs: list[str] = field(default_factory=list)       # artifact_ref list
    outputs: list[str] = field(default_factory=list)      # declared output kinds
    dependencies: list[str] = field(default_factory=list)  # depends-on task_ids
    provenance: list[str] = field(default_factory=list)   # upstream artifact ids
    cost_class: str | None = None
    concurrency_group: str | None = None
    max_retries: int = 3
    # F-11: Missing v4 §7 fields
    timeout: int | None = None              # wall-clock timeout in seconds
    heartbeat_interval: int = 30            # v4 §19: default 30s
    retry_policy: str = "FIXED"             # FIXED | EXPONENTIAL | NONE
    permissions: str | None = None          # tool allowlist / permission level
    # S13: Skip-rate fields (v4 §7/S13)
    sources_considered: int = 0
    sources_skipped: int = 0
    skip_reasons: str | None = None         # JSON serialize on persist
    skip_rate: float = 0.0
    created_at: str = ""
    started_at: str | None = None
    completed_at: str | None = None
    last_heartbeat: str | None = None

    def is_terminal(self) -> bool:
        """True if the node is in a terminal status."""
        return self.status in {
            TaskStatus.SUCCEEDED.value,
            TaskStatus.CANCELLED.value,
            TaskStatus.SKIPPED.value,
            TaskStatus.INVALIDATED.value,
        }

    def can_be_invalidated(self) -> bool:
        """A node can be invalidated if it has succeeded (v4 §7 rule 4)."""
        return self.status == TaskStatus.SUCCEEDED.value
