"""Append-only event journal (v4 §8.1) — command → validate → apply → event.

The event journal is the audit trail for every authoritative state mutation.
Events are append-only — no UPDATE or DELETE path is exposed through the
repository API. Every state-changing operation emits exactly one event within
the same SQLite transaction as the state change (IDR-013).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class EventType(str, Enum):
    """v4 §8.1 event catalog — the named events throughout v3 plus the
    supporting set. Not every event type is emitted in Phase 1; the full
    catalog is defined here for forward compatibility."""

    # Project lifecycle
    RESEARCH_CREATED = "ResearchCreated"
    LIFECYCLE_TRANSITION = "LifecycleTransition"
    MODE_CHANGED = "ModeChanged"
    PROJECT_PAUSED = "ProjectPaused"
    PROJECT_RESUMED = "ProjectResumed"
    RESEARCH_COMPLETED = "ResearchCompleted"
    BACKUP_SNAPSHOT = "BackupSnapshot"

    # Human gates (§9)
    HUMAN_APPROVAL_REQUESTED = "HumanApprovalRequested"
    HUMAN_GATE_RESOLVED = "HumanGateResolved"  # a ratified human verdict (APPROVED / REJECTED) on a parked HUMAN_GATE — the resolution that makes the three mandatory gates passable in shipped code (red-team A2)
    HUMAN_DECISION_RECEIVED = "HumanDecisionReceived"
    GATE_EXPIRED = "GateExpired"
    GATE_EVALUATED = "GateEvaluated"
    GATE_PASSED = "GatePassed"
    GATE_FAILED = "GateFailed"

    # Task lifecycle (§7)
    TASK_STATUS_CHANGED = "TaskStatusChanged"
    TASK_CREATED = "TaskCreated"
    TASK_INVALIDATED = "TaskInvalidated"
    HEARTBEAT_MISSED = "HeartbeatMissed"

    # Intent gateway (§8)
    INTENT_APPLIED = "IntentApplied"
    INTENT_REJECTED = "IntentRejected"

    # ResearchProgram (IDR-018) — emitted atomically with the program write
    RESEARCH_PROGRAM_COMPILED = "ResearchProgramCompiled"

    # Evidence (§10)
    EVIDENCE_TRANSITION_PROPOSED = "EvidenceTransitionProposed"  # ADV-05: declared in the v4 catalog, was enum-missing
    CLASSIFICATION_ACTION_PROPOSED = "ClassificationActionProposed"  # IDR-040: the Director proposed a Q-05 permitted action for a re-review candidate (proposal-only; acting still requires the existing authority)
    CLASSIFICATION_ACTION_DECISION = "ClassificationActionDecision"  # IDR-040: a ratified human decision on a pending classification-action proposal (APPROVED / REJECTED)
    SCOPE_REVIEW_DECIDED = "ScopeReviewDecided"  # IDR-041: the S16 scope-review intake — the human's scope verdict on an APPROVED ROUTE_TO_SCOPE_REVIEW / PROPOSE_SCOPE_NARROWING proposal (ratification ref = proposal_id)
    EVIDENCE_TRANSITION_APPLIED = "EvidenceTransitionApplied"
    REFUTED_APPLIED = "RefutedApplied"  # the bare-classification falsification fact (IDR-041 AC-2 driver 3): a digest-valid Q-05 classification ALONE certified a decisive falsification — first-class for event-catalog consumers, no ladder-row reads
    EVIDENCE_TRANSITION_REJECTED = "EvidenceTransitionRejected"
    CONTRADICTION_DETECTED = "ContradictionDetected"
    CONTRADICTION_RESOLVED = "ContradictionResolved"  # CHG-1: ratified human verdict resolving an OPEN contradiction (one-verdict; contradictory re-verdicts refused)
    CONTRADICTION_SUPERSEDED = "ContradictionSuperseded"  # CHG-1: an OPEN contradiction retired because a party went inactive or a newer contradiction superseded it (head-only, append-only)

    # Experiment lifecycle
    EXPERIMENT_PRE_REGISTERED = "ExperimentPreRegistered"
    EXPERIMENT_CREATED = "ExperimentCreated"
    EXPERIMENT_STARTED = "ExperimentStarted"
    EXPERIMENT_COMPLETED = "ExperimentCompleted"
    EXPERIMENT_FAILED = "ExperimentFailed"
    RESULT_GENERATED = "ResultGenerated"
    RESULT_REUSED = "ResultReused"

    # Recovery (§19)
    CIRCUIT_BREAKER_TRIPPED = "CircuitBreakerTripped"
    BUDGET_EXCEEDED = "BudgetExceeded"  # ADV-05: declared in the v4 catalog, was enum-missing
    SOURCE_RETRACTED = "SourceRetracted"  # ADV-05: declared in the v4 catalog, was enum-missing

    # Engineering (§20)
    ENGINEERING_CHANGE_REQUESTED = "ENGINEERING_CHANGE_REQUESTED"
    MERGED_CHANGE_RECORDED = "MergedChangeRecorded"
    MERGE_COMPLETED = "MergeCompleted"

    # Literature / data
    THESIS_INVESTIGATION_COMPLETED = "ThesisInvestigationCompleted"  # ADV-05: declared in the v4 catalog, was enum-missing
    QUESTION_APPROVED = "QuestionApproved"
    SCOPE_DEFINED = "ScopeDefined"
    SOURCE_DISCOVERED = "SourceDiscovered"
    LITERATURE_REVIEW_COMPLETED = "LiteratureReviewCompleted"
    HYPOTHESIS_CREATED = "HypothesisCreated"
    HYPOTHESIS_CRITIQUED = "HypothesisCritiqued"
    DATASET_REGISTERED = "DatasetRegistered"
    DATASET_VALIDATED = "DatasetValidated"
    DATASET_REJECTED = "DatasetRejected"
    FEATURE_BOUND = "FeatureBound"
    FEATURE_VERSIONED = "FeatureVersioned"

    # Analysis
    ANALYSIS_COMPLETED = "AnalysisCompleted"
    CRITIQUE_GENERATED = "CritiqueGenerated"
    REPLICATION_REQUESTED = "ReplicationRequested"
    REPLICATION_COMPLETED = "ReplicationCompleted"

    # Iteration (F-09)
    ITERATION_ADVANCED = "IterationAdvanced"  # ADV-05: EMITTED by the system, was enum-missing

    # Curated knowledge registry (Step 7, v6 §16.6) — the journally-derived
    # REFUTED_PATTERN reference index. Proposed+Admitted are emitted atomically
    # by the CURATE_KNOWLEDGE admission transaction (the proposal IS the
    # admission record — one write path, no second authority); Invalidated is
    # emitted inside the existing S5 RETRACT_SOURCE transaction when a
    # retraction cone reaches an ADMITTED entry's stored evidence basis.
    CURATED_KNOWLEDGE_PROPOSED = "CuratedKnowledgeProposed"
    CURATED_KNOWLEDGE_ADMITTED = "CuratedKnowledgeAdmitted"
    CURATED_KNOWLEDGE_INVALIDATED = "CuratedKnowledgeInvalidated"

    # Task ordering — C4 exploration floor (ratified design gate §4.3)
    FLOOR_GRANT_RECORDED = "FloorGrantRecorded"  # C4 §4.3: the durable floor-grant / F-C transition record — the ranking itself is transient (never persisted), so the floor's audit history rides this append-only event; the F-C stagnation counter is re-derived from these events + the satisfaction links, never stored


@dataclass(frozen=True, slots=True)
class EventRecord:
    """A single event in the append-only journal (v4 §8.1).

    This is the domain representation of a persisted event row. The
    repository maps between ``EventRecord`` and the ``events`` table;
    domain code never touches SQL directly (IDR-007).
    """

    event_id: int | None  # None before persistence (AUTOINCREMENT assigns)
    event_type: str
    project_id: str | None = None
    task_id: str | None = None
    from_state: str | None = None
    to_state: str | None = None
    correlation_id: str = ""
    caused_by: str = ""
    reason: str = ""
    artifact_ids: list[str] = field(default_factory=list)
    payload: dict[str, Any] = field(default_factory=dict)
    created_at: str = ""
