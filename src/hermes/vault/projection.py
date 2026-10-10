"""P-AUTO-5 vault projection — journal cursor over AUTOINCREMENT event_id.

Deterministic projector only: journal rows in, markdown notes out. No
model calls, no judgment — content is TRANSCRIBED from the row, never
generated. Every note is a derived view (labeled as such in its header),
never authority — the prohibited-claims discipline.

Two graphs, correctly labeled:
- authoritative: ratified/accepted fact classes with current validity
  (a later invalidating event moves the note to the process graph with a
  superseded pointer — unverified claims never appear here);
- process: everything else (tasks, refusals, gates, proposals, recovery),
  always ``authoritative: false``.

Invariants: one journal row → exactly one note (scratch == incremental);
stable file names from content IDs (never titles); alias-form wikilinks
only (``[[stable-id|human alias]]``); cursor = max event_id projected;
re-running a cursor range changes zero bytes; the projector never mutates
the journal (read-only SELECTs; no persistence imports, no new schema).

Every run also writes the derived-view manifest
(``.projection-manifest.json``, see ``hermes.vault.manifest``): the cursor
range, one digest per note the journal claims in that range, and the
journal-head anchor. The manifest is derived state, never authority —
``hermes vault verify`` recomputes it from the journal and refuses loudly,
naming the missing/invented IDs, when the vault and the journal disagree
(restored-ahead cursors, lost/backfilled ranges, tampered notes).
"""

from __future__ import annotations

import json
import logging
import os
import re
from typing import Any

__all__ = [
    "AUTHORITATIVE_EVENT_TYPES",
    "CURSOR_FILENAME",
    "HUMAN_OWNED_NAMES",
    "INVALIDATING_EVENT_TYPES",
    "PROJECTION_VERSION",
    "ProjectionRefused",
    "init_vault_root",
    "note_filename",
    "project",
    "read_cursor",
    "write_cursor",
]

PROJECTION_VERSION = "1"
CURSOR_FILENAME = ".projection-cursor"

logger = logging.getLogger(__name__)

# Human-owned areas — the projector never writes here (refuse, do not
# touch). Matched against resolved path components (case-insensitive).
HUMAN_OWNED_NAMES: tuple[str, ...] = ("obsidian-vault", "reports", "Prompts")

# Ratified/accepted fact classes (authoritative graph candidates).
AUTHORITATIVE_EVENT_TYPES: tuple[str, ...] = (
    "HumanDecisionReceived",
    "HumanGateResolved",
    "EvidenceTransitionApplied",
    "CuratedKnowledgeAdmitted",
    "ContradictionResolved",
)

# Events that retire an earlier authoritative fact (same subject).
INVALIDATING_EVENT_TYPES: tuple[str, ...] = (
    "TaskInvalidated",
    "CuratedKnowledgeInvalidated",
    "SourceRetracted",
    "ContradictionSuperseded",
)

# Payload keys that may identify the invalidated subject (closed set).
# ``artifact_id`` shares the ``artifact:`` namespace with ``artifact_ids_json``
# so a retraction can retire an admission that records the same ref (B3).
_SUBJECT_PAYLOAD_KEYS: tuple[str, ...] = ("entry_id", "source", "ref",
                                          "artifact_id")

# Production payload keys (C-F-01): the writers emit subject identifiers the
# legacy closed set never matched, so validity was inert for the task-less
# authoritative classes. Each key below is namespaced to the event types
# that OWN the identifier (same-namespace victim/invalidator pairing only
# — no cross-namespace retirement, no HumanDecision retirement):
# - ``curated_id``: CuratedKnowledgeAdmitted (gateway.py admission_payload)
#   retired by CuratedKnowledgeInvalidated (gateway.py S5 follow-on);
# - ``contradiction_id``: ContradictionResolved (gateway.py resolution)
#   retired by ContradictionSuperseded (gateway.py S5 follow-on / record
#   supersession);
# - ``program_id``+``hypothesis_ref``: EvidenceTransitionApplied
#   (controller.py ladder write, task-less) identity — no production
#   invalidator carries the ladder key today, so the fact stays live but
#   is at least RECOGNIZED (non-empty subjects) instead of inert;
# - ``source_artifact_id``: SourceRetracted / CuratedKnowledgeInvalidated /
#   TaskInvalidated (S5 cascade) artifact identity (shares ``artifact:``).
# Deliberately EXCLUDED (needs product judgment, out of scope):
# ``retraction_id`` (would retire the authorizing HumanDecision via its own
# cascade), evidence-basis lists (would retire beyond the gateway's
# explicit invalidation events), ``superseded_by`` (the new head's id).
_CURATED_SUBJECT_TYPES: tuple[str, ...] = (
    "CuratedKnowledgeAdmitted", "CuratedKnowledgeInvalidated")
_CONTRADICTION_SUBJECT_TYPES: tuple[str, ...] = (
    "ContradictionResolved", "ContradictionSuperseded")
_LADDER_SUBJECT_TYPES: tuple[str, ...] = ("EvidenceTransitionApplied",)
_SOURCE_ARTIFACT_SUBJECT_TYPES: tuple[str, ...] = (
    "SourceRetracted", "CuratedKnowledgeInvalidated", "TaskInvalidated")

# Human verdicts that REFUSE a claim — a refusing resolution is a process
# record, never a currently-valid authoritative fact (A1).
_NON_ACCEPTING_VERDICTS: frozenset[str] = frozenset({
    "REJECTED", "REJECT", "DENIED", "REFUSED", "FAILED", "VETOED", "REVOKED",
})

# Bound for any single transcribed field (the journal's own 4 KiB rule,
# applied to derived note writes).
_FIELD_LIMIT = 4096

# Closed per-class summary lines (structure only — the row supplies facts).
_EVENT_SUMMARIES: dict[str, str] = {
    "ResearchCreated": "Research project created",
    "LifecycleTransition": "Lifecycle transition recorded",
    "ModeChanged": "Operational mode changed",
    "ProjectPaused": "Project paused",
    "ProjectResumed": "Project resumed",
    "ResearchCompleted": "Research completed",
    "BackupSnapshot": "Backup snapshot recorded",
    "HumanApprovalRequested": "Human approval requested (gate parked)",
    "HumanGateResolved": "Human gate resolved (ratified verdict)",
    "HumanDecisionReceived": "Human decision received (ratified)",
    "GateExpired": "Gate expired",
    "GateEvaluated": "Gate evaluated",
    "GatePassed": "Gate passed",
    "GateFailed": "Gate failed",
    "TaskStatusChanged": "Task status changed",
    "TaskCreated": "Task created",
    "TaskInvalidated": "Task invalidated",
    "HeartbeatMissed": "Heartbeat missed",
    "IntentApplied": "Intent applied",
    "IntentRejected": "Intent refused",
    "ResearchProgramCompiled": "Research program compiled",
    "EvidenceTransitionProposed": "Evidence transition proposed",
    "ClassificationActionProposed": "Classification action proposed",
    "ClassificationActionDecision": "Classification action decided",
    "ScopeReviewDecided": "Scope review decided",
    "EvidenceTransitionApplied": "Evidence transition applied (ratified fact)",
    "RefutedApplied": "Refutation applied",
    "EvidenceTransitionRejected": "Evidence transition rejected",
    "ContradictionDetected": "Contradiction detected",
    "ContradictionResolved": "Contradiction resolved (ratified verdict)",
    "ContradictionSuperseded": "Contradiction superseded",
    "ExperimentPreRegistered": "Experiment pre-registered",
    "ExperimentCreated": "Experiment created",
    "ExperimentStarted": "Experiment started",
    "ExperimentCompleted": "Experiment completed",
    "ExperimentFailed": "Experiment failed",
    "ResultGenerated": "Result generated",
    "ResultReused": "Result reused",
    "CircuitBreakerTripped": "Circuit breaker tripped",
    "BudgetExceeded": "Budget exceeded",
    "SourceRetracted": "Source retracted",
    "ENGINEERING_CHANGE_REQUESTED": "Engineering change requested",
    "MergedChangeRecorded": "Merged change recorded",
    "MergeCompleted": "Merge completed",
    "ThesisInvestigationCompleted": "Thesis investigation completed",
    "QuestionApproved": "Question approved",
    "ScopeDefined": "Scope defined",
    "SourceDiscovered": "Source discovered",
    "LiteratureReviewCompleted": "Literature review completed",
    "HypothesisCreated": "Hypothesis created",
    "HypothesisCritiqued": "Hypothesis critiqued",
    "DatasetRegistered": "Dataset registered",
    "DatasetValidated": "Dataset validated",
    "DatasetRejected": "Dataset rejected",
    "FeatureBound": "Feature bound",
    "FeatureVersioned": "Feature versioned",
    "AnalysisCompleted": "Analysis completed",
    "CritiqueGenerated": "Critique generated",
    "ReplicationRequested": "Replication requested",
    "ReplicationCompleted": "Replication completed",
    "IterationAdvanced": "Iteration advanced",
    "CuratedKnowledgeProposed": "Curated knowledge proposed",
    "CuratedKnowledgeAdmitted": "Curated knowledge admitted",
    "CuratedKnowledgeInvalidated": "Curated knowledge invalidated",
    "FloorGrantRecorded": "Floor grant recorded",
}


# The journal columns the projector reads (SELECT shape shared by the
# window / head / full-range queries, so the head hash and the note digests
# are computed from the same row projection).
_COLUMNS = (
    "event_id, event_type, project_id, task_id, from_state, to_state, "
    "correlation_id, caused_by, reason, artifact_ids_json, payload_json, "
    "created_at"
)


class ProjectionRefused(Exception):
    """A refusal with a closed-set code — refusal-as-data, never silent."""

    def __init__(self, code: str, detail: str) -> None:
        self.code = code
        self.detail = detail
        super().__init__(f"projection refused [{code}]: {detail}")


def _slug(event_type: str) -> str:
    """Deterministic CamelCase → kebab slug for file names."""
    slug = re.sub(r"(?<!^)(?=[A-Z])", "-", event_type).lower()
    slug = re.sub(r"[^a-z0-9]+", "-", slug).strip("-")
    return slug or "event"


def note_filename(event_id: int, event_type: str) -> str:
    """Stable note name from the content ID (never a title)."""
    if not isinstance(event_id, int) or isinstance(event_id, bool) \
            or event_id < 1:
        raise ProjectionRefused(
            "BAD_EVENT_ID",
            f"event_id must be a positive int, got {event_id!r}")
    return f"evt-{event_id:06d}-{_slug(str(event_type))}.md"


def note_stem(event_id: int, event_type: str) -> str:
    """Wikilink target for a note (extensionless stable ID)."""
    return note_filename(event_id, event_type)[:-len(".md")]


def _bound_text(value: object) -> str:
    """Transcribe one field, bounded at 4 KiB with an explicit marker."""
    text = "" if value is None else str(value)
    if len(text) > _FIELD_LIMIT:
        return text[:_FIELD_LIMIT] + "…[truncated: field exceeded 4096 chars]"
    return text


def _normcase(path: str) -> str:
    return os.path.normcase(os.path.normpath(path))


def init_vault_root(vault_root: str) -> str:
    """Validate + jail the vault root; return its resolved absolute path.

    Refusals (named codes): VAULT_ROOT_NOT_ABSOLUTE (jail needs an
    absolute root), VAULT_ROOT_HUMAN_OWNED (resolved root is or sits under
    a human-owned area — never written). The root is created (parents
    included) only after both checks pass.
    """
    if not os.path.isabs(vault_root):
        raise ProjectionRefused(
            "VAULT_ROOT_NOT_ABSOLUTE",
            f"vault root must be absolute, got {vault_root!r}")
    resolved = os.path.realpath(vault_root)
    parts = [p for p in _normcase(resolved).split(os.sep) if p]
    # Case-insensitive on every platform (human-owned names are a human
    # convention — OBSIDIAN-VAULT must refuse exactly like obsidian-vault).
    owned = {name.casefold() for name in HUMAN_OWNED_NAMES}

    def _is_human_owned(part: str) -> bool:
        folded = part.casefold()
        # Win32 strips trailing dots/spaces from every component before the
        # filesystem sees the name, so ``reports.``/``reports `` would create
        # ``reports`` — compare the normalized form and refuse before mkdir (C1).
        return folded in owned \
            or (os.name == "nt" and folded.rstrip(" .") in owned)

    if any(_is_human_owned(p) for p in parts):
        raise ProjectionRefused(
            "VAULT_ROOT_HUMAN_OWNED",
            f"vault root {resolved!r} is inside a human-owned area "
            f"{sorted(HUMAN_OWNED_NAMES)} — never written")
    os.makedirs(resolved, exist_ok=True)
    return resolved


def _join_note(resolved_root: str, filename: str) -> str:
    """Join a generated file name under the jailed root (guard battery).

    Refusals: PATH_ESCAPE (resolved path leaves the root — ../, absolute,
    or case-trick paths), SYMLINK_ESCAPE (a pre-planted symlink at the
    note path — never write through), PATH_CONFLICT (a directory blocks
    the note path).
    """
    lexical = os.path.join(resolved_root, filename)
    # Pre-resolution alias checks (C2): realpath() hides an in-root symlink
    # behind its target and cannot see hard links at all, so the lexical note
    # path is tested first — a planted alias is refused, never written through.
    if os.path.lexists(lexical) and os.path.islink(lexical):
        raise ProjectionRefused(
            "SYMLINK_ESCAPE",
            f"note path {lexical!r} is a symlink — never write through")
    if os.path.lexists(lexical) and not os.path.isdir(lexical) \
            and getattr(os.stat(lexical), "st_nlink", 1) > 1:
        raise ProjectionRefused(
            "ALIAS_ESCAPE",
            f"note path {lexical!r} is hard-linked to another file — "
            "refusing to clobber an aliased note")
    candidate = os.path.realpath(lexical)
    # Lexical parent escape first (platform-independent: backslash tricks
    # must refuse on posix too, where "\\" is otherwise a plain character).
    raw_parts = re.split(r"[\\/]", filename)
    if any(part == ".." for part in raw_parts):
        raise ProjectionRefused(
            "PATH_ESCAPE",
            f"note name {filename!r} climbs above the vault root")
    prefix = resolved_root + os.sep
    if candidate != resolved_root and not candidate.startswith(prefix):
        raise ProjectionRefused(
            "PATH_ESCAPE",
            f"note path {candidate!r} escapes vault root {resolved_root!r}")
    if os.path.lexists(candidate) and os.path.islink(candidate):
        raise ProjectionRefused(
            "SYMLINK_ESCAPE",
            f"note path {candidate!r} is a symlink — never write through")
    if os.path.isdir(candidate):
        raise ProjectionRefused(
            "PATH_CONFLICT",
            f"note path {candidate!r} is a directory")
    return candidate


def _row_subject_keys(row: dict[str, Any]) -> frozenset[str]:
    """Closed subject-key set for validity matching (deterministic)."""
    keys: set[str] = set()
    task_id = row.get("task_id")
    if isinstance(task_id, str) and task_id:
        keys.add(f"task:{task_id}")
    raw_artifacts = row.get("artifact_ids_json")
    if isinstance(raw_artifacts, str) and raw_artifacts:
        try:
            parsed_artifacts = json.loads(raw_artifacts)
        except ValueError:
            parsed_artifacts = []
        if isinstance(parsed_artifacts, list):
            keys.update(f"artifact:{a}" for a in parsed_artifacts
                        if isinstance(a, str) and a)
    raw_payload = row.get("payload_json")
    parsed_payload: dict[str, Any] = {}
    if isinstance(raw_payload, str) and raw_payload:
        try:
            loaded = json.loads(raw_payload)
        except ValueError:
            loaded = {}
        if isinstance(loaded, dict):
            parsed_payload = loaded
            for key in _SUBJECT_PAYLOAD_KEYS:
                value = parsed_payload.get(key)
                if isinstance(value, str) and value:
                    if key == "artifact_id":
                        keys.add(f"artifact:{value}")
                    else:
                        keys.add(f"payload:{key}:{value}")
    # C-F-01 production keys (type-scoped, same-namespace only).
    event_type = row.get("event_type")
    if isinstance(event_type, str) and parsed_payload:
        if event_type in _CURATED_SUBJECT_TYPES:
            curated_id = parsed_payload.get("curated_id")
            if isinstance(curated_id, str) and curated_id:
                keys.add(f"curated:{curated_id}")
        if event_type in _CONTRADICTION_SUBJECT_TYPES:
            contradiction_id = parsed_payload.get("contradiction_id")
            if isinstance(contradiction_id, str) and contradiction_id:
                keys.add(f"contradiction:{contradiction_id}")
        if event_type in _LADDER_SUBJECT_TYPES:
            program_id = parsed_payload.get("program_id")
            if not isinstance(program_id, str) or not program_id:
                program_ref = parsed_payload.get("program_ref")
                program_id = program_ref if isinstance(
                    program_ref, str) else ""
            hypothesis_ref = parsed_payload.get("hypothesis_ref")
            if (isinstance(program_id, str) and program_id
                    and isinstance(hypothesis_ref, str)
                    and hypothesis_ref):
                keys.add(f"ladder:{program_id}:{hypothesis_ref}")
        if event_type in _SOURCE_ARTIFACT_SUBJECT_TYPES:
            source_artifact_id = parsed_payload.get("source_artifact_id")
            if isinstance(source_artifact_id, str) and source_artifact_id:
                keys.add(f"artifact:{source_artifact_id}")
    return frozenset(keys)


def _payload_text(row: dict[str, Any]) -> str:
    """Deterministic payload transcription (sorted keys, or "" when absent)."""
    raw = row.get("payload_json")
    if not isinstance(raw, str) or not raw:
        return ""
    try:
        parsed = json.loads(raw)
    except ValueError:
        return _bound_text(raw)
    return _bound_text(json.dumps(parsed, sort_keys=True, separators=(",", ":")))


def _payload_dict(row: dict[str, Any]) -> dict[str, Any]:
    """Parsed payload object (empty when absent or corrupt — deterministic)."""
    raw = row.get("payload_json")
    if not isinstance(raw, str) or not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except ValueError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _rejects(row: dict[str, Any]) -> bool:
    """True when the row carries a refusing human verdict (A1).

    Production writers split the verdict across two keys:
    HumanDecisionReceived emits ``decision``
    (controller.py:2186,2335,2550,2692) while HumanGateResolved
    emits ``verdict`` (controller.py:1923). Both share the refusing
    vocabulary in _NON_ACCEPTING_VERDICTS.
    """
    payload = _payload_dict(row)
    for key in ("decision", "verdict"):
        value = payload.get(key)
        if isinstance(value, str) \
                and value.strip().upper() in _NON_ACCEPTING_VERDICTS:
            return True
    return False


def _is_authoritative(row: dict[str, Any]) -> bool:
    """Authority = accepted fact class with no refusing verdict."""
    return (row.get("event_type") in AUTHORITATIVE_EVENT_TYPES
            and not _rejects(row))


def _header_value(value: object) -> str:
    """JSON-encoded single-line frontmatter scalar.

    JSON strings are valid YAML double-quoted scalars, so a hostile
    ``task_id``/``created_at`` cannot inject a newline, a ``---`` document
    delimiter, or a duplicate ``authoritative`` key into the header (A2/F).
    """
    encoded = json.dumps("" if value is None else str(value))
    # JSON leaves brackets literal; unicode-escape them so a hostile row can
    # never render a wikilink anywhere in the note, frontmatter included (A2/D1).
    return encoded.replace("[", r"\u005b").replace("]", r"\u005d")


def _single_line(text: str) -> str:
    """Render one transcript line: real newlines become visible markers.

    The body must never grow structure the projector did not put there — a
    hostile reason/task_id containing a fake label line stays one transcribed
    line (A2/F).
    """
    return text.replace("\r\n", "\\n").replace("\r", "\\n").replace(
        "\n", "\\n")


def _escape_links(text: str) -> str:
    """Neutralize wikilink syntax in transcribed text (D1)."""
    return text.replace("[[", r"\[\[").replace("]]", r"\]\]")


_STABLE_STEM_RE = re.compile(r"evt-\d{6,}-[a-z0-9-]+\Z")
_WIKILINK_TARGET_RE = re.compile(r"(?<!\\)\[\[([^\]|]+)")


def _assert_stable_links(body: str, filename: str) -> None:
    """Refuse a note whose unescaped wikilink leaves the stable-ID space (D1)."""
    for target in _WIKILINK_TARGET_RE.findall(body):
        if not _STABLE_STEM_RE.match(target):
            raise ProjectionRefused(
                "LINK_ESCAPE",
                f"{filename}: wikilink target {target!r} is outside the "
                "stable-ID namespace")


def _render(row: dict[str, Any], *, authoritative: bool,
            currently_valid: bool, links: list[str]) -> str:
    """Render one note (pure function of the row + verdict + links)."""
    event_id = row["event_id"]
    event_type = str(row.get("event_type") or "Event")
    summary = _EVENT_SUMMARIES.get(event_type, "Event recorded")
    task_id = row.get("task_id") or ""
    lines = [
        "---",
        "projection: hermes-vault-projection/v1",
        f"event_id: {event_id}",
        f"event_type: {_header_value(event_type)}",
        f"project_id: {_header_value(row.get('project_id') or '')}",
        f"task_id: {_header_value(task_id)}",
        f"authoritative: {'true' if authoritative else 'false'}",
    ]
    if authoritative:
        lines.append(f"currently_valid: {'true' if currently_valid else 'false'}")
    lines += [
        f"created_at: {_header_value(row.get('created_at') or '')}",
        "---",
        "",
        "> Derived view — transcribed from the journal, never authority.",
    ]
    if not authoritative:
        lines.append("> Process record (authoritative: false).")
    lines += [
        "",
        f"# {summary}",
        "",
        (f"- event: #{event_id} "
         f"({_escape_links(_single_line(event_type))})"),
    ]
    if task_id:
        lines.append(
            f"- task: {_escape_links(_single_line(str(task_id)))}")
    from_state = row.get("from_state") or ""
    to_state = row.get("to_state") or ""
    if from_state or to_state:
        lines.append(
            "- transition: "
            f"{_escape_links(_single_line(str(from_state)))} -> "
            f"{_escape_links(_single_line(str(to_state)))}")
    reason = _bound_text(row.get("reason") or "")
    if reason:
        lines.append(f"- reason: {_escape_links(_single_line(reason))}")
    payload_text = _payload_text(row)
    if payload_text:
        lines.append(f"- payload: {_escape_links(_single_line(payload_text))}")
    caused_by = row.get("caused_by") or ""
    if caused_by:
        lines.append(
            f"- caused_by: {_escape_links(_single_line(str(caused_by)))}")
    for link in links:
        lines.append(f"- see: {link}")
    lines.append("")
    return "\n".join(lines)


def _task_alias(task_id: str) -> str:
    """Display alias with link syntax neutralized (a task id can be hostile)."""
    alias = re.sub(r"[\[\]|\r\n]+", " ", task_id).strip()
    return f"task {alias}" if alias else "task"


def _see_links(row: dict[str, Any], event_id: int,
               created: dict[str, int],
               invalidator: dict[str, Any] | None) -> list[str]:
    """Canonical see-link emission — ONE path for window and rewrite (B2)."""
    links: list[str] = []
    task_id = row.get("task_id")
    if isinstance(task_id, str) and task_id and task_id in created \
            and created[task_id] != event_id:
        target = note_stem(created[task_id], "TaskCreated")
        links.append(f"[[{target}|{_task_alias(task_id)}]]")
    if invalidator is not None:
        target = note_stem(invalidator["event_id"],
                           str(invalidator.get("event_type")))
        links.append(
            f"[[{target}|superseded by #{invalidator['event_id']}]]")
    return links


def _window_rows(conn: Any, project_id: str,
                 cursor: int) -> list[dict[str, Any]]:
    """Journal rows for one project with event_id > cursor (read-only)."""
    rows = conn.execute(
        f"SELECT {_COLUMNS} FROM events "
        "WHERE project_id = ? AND event_id > ? ORDER BY event_id ASC",
        (project_id, cursor),
    ).fetchall()
    return [dict(row) for row in rows]


def _journal_head(conn: Any, project_id: str) -> dict[str, Any] | None:
    """The project's highest journal row (read-only), or None when empty."""
    row = conn.execute(
        f"SELECT {_COLUMNS} FROM events WHERE project_id = ? "
        "ORDER BY event_id DESC LIMIT 1",
        (project_id,),
    ).fetchone()
    return None if row is None else dict(row)


def _created_index(conn: Any, project_id: str) -> dict[str, int]:
    """First TaskCreated event_id per task (link-target resolution)."""
    created: dict[str, int] = {}
    rows = conn.execute(
        "SELECT event_id, task_id FROM events "
        "WHERE project_id = ? AND event_type = 'TaskCreated' "
        "ORDER BY event_id ASC",
        (project_id,),
    ).fetchall()
    for row in rows:
        task_id = row["task_id"]
        event_id = row["event_id"]
        if isinstance(task_id, str) and task_id \
                and isinstance(event_id, int) and task_id not in created:
            created[task_id] = event_id
    return created


def _invalidated_by(conn: Any, project_id: str,
                    horizon: int) -> dict[int, int]:
    """victim event_id -> invalidator event_id, over history <= horizon."""
    auth_marks = ",".join("?" for _ in AUTHORITATIVE_EVENT_TYPES)
    inval_marks = ",".join("?" for _ in INVALIDATING_EVENT_TYPES)
    rows = conn.execute(
        "SELECT event_id, event_type, task_id, artifact_ids_json, "
        "payload_json FROM events WHERE project_id = ? AND event_id <= ? "
        f"AND (event_type IN ({auth_marks}) OR event_type IN ({inval_marks})) "
        "ORDER BY event_id ASC",
        (project_id, horizon, *AUTHORITATIVE_EVENT_TYPES,
         *INVALIDATING_EVENT_TYPES),
    ).fetchall()
    # Two passes over one deterministic order: later invalidating rows
    # retire earlier authoritative facts on shared subject keys. Row order
    # is causal — a pre-cursor invalidation never retires a later fact.
    invalidated_by: dict[int, int] = {}  # invalidated event_id -> invalidator
    live_subjects: dict[str, int] = {}
    for history_row in rows:
        past = dict(history_row)
        past_id = past["event_id"]
        subjects = _row_subject_keys(past)
        if past.get("event_type") in INVALIDATING_EVENT_TYPES:
            for key in subjects:
                if key in live_subjects:
                    invalidated_by[live_subjects[key]] = past_id
                    del live_subjects[key]
        elif subjects and _is_authoritative(past):
            for key in subjects:
                live_subjects[key] = past_id
    return invalidated_by


def _window_plans(rows: list[dict[str, Any]], created: dict[str, int],
                  invalidated_by: dict[int, int]) -> list[tuple[int, str, str]]:
    """Plan ``(event_id, filename, body)`` for a contiguous row window."""
    by_id = {row["event_id"]: row for row in rows}
    plans: list[tuple[int, str, str]] = []
    for row in rows:
        event_id = row["event_id"]
        event_type = str(row.get("event_type") or "Event")
        accepted = _is_authoritative(row)
        invalidated = invalidated_by.get(event_id) if accepted else None
        if invalidated is not None and invalidated not in by_id:
            raise ProjectionRefused(
                "INVALIDATOR_MISSING",
                f"invalidator #{invalidated} for window row #{event_id} is "
                "not in the projected window")
        invalidator = by_id[invalidated] if invalidated is not None else None
        plans.append((
            event_id,
            note_filename(event_id, event_type),
            _render(row, authoritative=accepted and invalidator is None,
                    currently_valid=True,
                    links=_see_links(row, event_id, created, invalidator)),
        ))
    return plans


def _stale_plans(conn: Any, project_id: str, created: dict[str, int],
                 invalidated_by: dict[int, int],
                 window_ids: set[int]) -> list[tuple[int, str, str]]:
    """Late-invalidation rewrites for victims outside the window (B1/B2).

    The invalidator is queried from the journal by id (never indexed through
    the window) and link emission is shared with the in-window path, so a
    consumed invalidation cannot wedge a later catch-up and the rewrite is
    byte-identical to scratch.
    """
    stale_victims = sorted(
        victim for victim in invalidated_by if victim not in window_ids)
    plans: list[tuple[int, str, str]] = []
    if not stale_victims:
        return plans
    placeholders = ",".join("?" for _ in stale_victims)
    victim_rows = conn.execute(
        "SELECT event_id, event_type, project_id, task_id, from_state, "
        "to_state, correlation_id, caused_by, reason, artifact_ids_json, "
        "payload_json, created_at FROM events "
        f"WHERE project_id = ? AND event_id IN ({placeholders}) "
        "ORDER BY event_id ASC",
        (project_id, *stale_victims),
    ).fetchall()
    victims = {row["event_id"]: dict(row) for row in victim_rows}
    missing_victims = [v for v in stale_victims if v not in victims]
    if missing_victims:
        raise ProjectionRefused(
            "VICTIM_MISSING",
            f"invalidated rows {missing_victims} are absent from the "
            "journal — refusing an unverifiable supersede")
    invalidator_ids = sorted({invalidated_by[v] for v in stale_victims})
    inv_marks = ",".join("?" for _ in invalidator_ids)
    inv_rows = conn.execute(
        "SELECT event_id, event_type FROM events "
        f"WHERE project_id = ? AND event_id IN ({inv_marks})",
        (project_id, *invalidator_ids),
    ).fetchall()
    invalidators = {row["event_id"]: dict(row) for row in inv_rows}
    missing_invalidators = [i for i in invalidator_ids
                            if i not in invalidators]
    if missing_invalidators:
        raise ProjectionRefused(
            "INVALIDATOR_MISSING",
            f"invalidator rows {missing_invalidators} are absent from "
            "the journal — cannot render a supersede link")
    for victim_id in stale_victims:
        victim = victims[victim_id]
        invalidator = invalidators[invalidated_by[victim_id]]
        plans.append((
            victim_id,
            note_filename(victim_id, str(victim.get("event_type"))),
            _render(victim, authoritative=False, currently_valid=False,
                    links=_see_links(victim, victim_id, created,
                                     invalidator)),
        ))
    return plans


def _plan_range(conn: Any, project_id: str,
                upper: int) -> list[tuple[int, str, str]]:
    """Scratch-equivalent plan over the FULL range (0, upper] — writes nothing.

    This is the manifest's claim: one note per journal row in the range,
    rendered by the same planner a scratch run uses (the pinned
    scratch == incremental invariant, so the digests certify catch-up runs
    too). Public to the vault package: the manifest verifier recomputes
    through it instead of trusting the manifest file.
    """
    if upper < 1:
        return []
    rows = conn.execute(
        f"SELECT {_COLUMNS} FROM events "
        "WHERE project_id = ? AND event_id <= ? ORDER BY event_id ASC",
        (project_id, upper),
    ).fetchall()
    row_dicts = [dict(row) for row in rows]
    if not row_dicts:
        return []
    return _window_plans(row_dicts, _created_index(conn, project_id),
                         _invalidated_by(conn, project_id, upper))


def _write_run_manifest(conn: Any, project_id: str, root: str, *,
                        cursor_before: int, cursor_after: int,
                        written: list[str]) -> None:
    """Write the derived-view manifest for this run (D2/G closure).

    The claim is recomputed from the journal, never guessed: every project
    row in ``(0, cursor_after]`` must have exactly one note whose digest is
    the rendered body. Notes this run did not write (below the cursor) are
    checked on disk here so an incomplete vault is loud at run time too;
    ``hermes vault verify`` is the refusing surface.
    """
    from hermes.vault.manifest import (
        build_manifest,
        journal_gap_event_ids,
        write_manifest,
    )
    entries = _plan_range(conn, project_id, cursor_after)
    head_row = _journal_head(conn, project_id)
    gaps = journal_gap_event_ids(conn, cursor_after)
    write_manifest(root, build_manifest(
        project_id=project_id, cursor_before=cursor_before,
        cursor_after=cursor_after, head_row=head_row, entries=entries,
        gap_event_ids=gaps))
    if gaps:
        logger.warning(
            "projection manifest for project %s records %d journal hole(s) "
            "in (0, %d] (event_id slots %s) — their notes can never be "
            "projected", project_id, len(gaps), cursor_after, list(gaps[:20]))
    # Run-time loudness for notes this run did not materialize (below-cursor
    # rows, restored cursors, prior edits). The verifier recomputes the same
    # facts from the journal instead of trusting the manifest.
    just_written = set(written)
    missing: list[int] = []
    diverged: list[int] = []
    for event_id, filename, body in entries:
        if filename in just_written:
            continue
        try:
            with open(os.path.join(root, filename), "rb") as handle:
                on_disk = handle.read()
        except OSError:
            missing.append(event_id)
            continue
        if on_disk != body.encode("utf-8"):
            diverged.append(event_id)
    if missing:
        logger.warning(
            "projection manifest: %d note(s) claimed for rows below the "
            "cursor are absent from the vault (event_ids %s) — the derived "
            "view is incomplete; `hermes vault verify` refuses loudly",
            len(missing), list(missing[:20]))
    if diverged:
        logger.warning(
            "projection manifest: %d note(s) diverge from the journal "
            "render (event_ids %s) — edited outside the projector; "
            "`hermes vault verify` refuses loudly",
            len(diverged), list(diverged[:20]))


def project(conn: Any, project_id: str, vault_root: str,
            cursor: int = 0) -> tuple[int, list[str]]:
    """Project journal rows (event_id > cursor) for one project to notes.

    Read-only over the journal (SELECTs only — the single mutation path is
    untouched, no schema, no intents). Returns ``(new_cursor, written)``
    where ``written`` lists note file names in event_id order. Determinism:
    the same rows always render byte-identical notes, so rerunning a cursor
    range changes zero bytes and scratch == incremental catch-up.
    """
    if not isinstance(cursor, int) or isinstance(cursor, bool) or cursor < 0:
        raise ProjectionRefused(
            "BAD_CURSOR", f"cursor must be a non-negative int, got {cursor!r}")
    if not isinstance(project_id, str) or not project_id:
        raise ProjectionRefused(
            "BAD_PROJECT_ID", f"project_id must be non-empty, got {project_id!r}")
    root = init_vault_root(vault_root)
    rows = _window_rows(conn, project_id, cursor)
    if not rows:
        head_row = _journal_head(conn, project_id)
        journal_max = None if head_row is None else head_row["event_id"]
        if journal_max is not None and cursor > journal_max:
            logger.warning(
                "projection cursor %d is ahead of journal max event_id %d for "
                "project %s — backfilled rows below the cursor can never be "
                "projected; the manifest records the ahead range and "
                "`hermes vault verify` refuses loudly",
                cursor, journal_max, project_id)
        _write_run_manifest(conn, project_id, root, cursor_before=cursor,
                            cursor_after=cursor, written=[])
        return cursor, []

    # Creation links span the FULL journal (not just the window): an
    # incremental run must render byte-identical notes to a scratch run,
    # so task-creation targets resolve the same at every cursor.
    created = _created_index(conn, project_id)
    # Validity over FULL history (not just the window): a victim projected
    # authoritative by an earlier run must still be retired when its
    # invalidator lands in a later window — otherwise scratch and
    # incremental runs diverge. Only fact/invalidation classes are read
    # (the full row set is never needed for the verdict).
    max_id = max(row["event_id"] for row in rows)
    expected_slots = max_id - cursor
    if expected_slots > len(rows):
        logger.warning(
            "projection gap for project %s in (%d, %d]: %d of %d event_id "
            "slot(s) absent (compacted or lost) — skipped loudly",
            project_id, cursor, max_id, expected_slots - len(rows),
            expected_slots)
    invalidated_by = _invalidated_by(conn, project_id, max_id)

    # Plan every write before touching disk: path-guard refusals, link-
    # namespace refusals and missing invalidator/victim rows abort the whole
    # run, never leaving a partially written window (B1).
    plans = _window_plans(rows, created, invalidated_by)
    # Late invalidation: a victim projected by an EARLIER run (event_id <=
    # cursor, outside this window) is rewritten as a superseded process note.
    # The invalidator may also lie outside the window (its row was already
    # projected) — it is looked up in the journal instead of assumed in-window,
    # so a consumed invalidation can never wedge later catch-ups (B1). Link
    # emission is shared with the in-window path, so the rewrite is
    # byte-identical to scratch (B2) and idempotent on every re-run.
    window_ids = {row["event_id"] for row in rows}
    plans.extend(_stale_plans(conn, project_id, created, invalidated_by,
                              window_ids))
    planned: list[tuple[int, str, str, str]] = []
    for event_id, filename, body in plans:
        _assert_stable_links(body, filename)
        planned.append((event_id, filename, _join_note(root, filename), body))
    written: list[str] = []
    for _event_id, filename, path, body in planned:
        with open(path, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(body)
        written.append(filename)
    written.sort(key=lambda name: int(name.split("-")[1]))
    _write_run_manifest(conn, project_id, root, cursor_before=cursor,
                        cursor_after=max_id, written=written)
    return max_id, written


def read_cursor(vault_root: str) -> int:
    """Read the persisted cursor (0 when absent — full projection)."""
    root = init_vault_root(vault_root)
    path = _join_note(root, CURSOR_FILENAME)
    if not os.path.exists(path):
        return 0  # no persisted position yet — the caller projects from 0
    try:
        with open(path, encoding="utf-8") as handle:
            return int(handle.read().strip() or "0")
    except (OSError, ValueError) as exc:
        raise ProjectionRefused(
            "BAD_CURSOR_FILE",
            f"cursor file unreadable: {exc}") from None


def write_cursor(vault_root: str, cursor: int) -> None:
    """Persist the cursor (projector-owned state, single int + newline)."""
    if not isinstance(cursor, int) or isinstance(cursor, bool) or cursor < 0:
        raise ProjectionRefused(
            "BAD_CURSOR", f"cursor must be a non-negative int, got {cursor!r}")
    root = init_vault_root(vault_root)
    path = _join_note(root, CURSOR_FILENAME)
    with open(path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(f"{cursor}\n")
