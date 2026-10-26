"""Diagnostic run report — what an operator reads when a live run fails (OPS-10).

The refusal codes that explain a failed run live in the runtime's in-memory
supervisor trace. This module writes them, with the model ledger, stage
outcomes and the CLI's vector line, to **one JSON file per run** at the run
boundary.

It is a diagnostic artifact, **not a record**: it is never read back as
authority, never replayed, never consulted by a validator, and the file says so
in its header. The append-only journal remains the one durable record. Nothing
here touches the database, opens a transaction, or imports the research plane.

Bounded by construction: every refused-reply excerpt is capped (default 2 000
UTF-8 bytes) and the file is capped (default 1 MiB); when lists do not fit,
they are truncated with a counted ``*_omitted`` marker rather than growing
unbounded. A write failure is the caller's to report and never changes a run's
exit code.
"""

from __future__ import annotations

import contextlib
import copy
import json
import os
import re
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from hermes.agents.runtime.types import TaskStatus
from hermes.core.intents import IntentKind
from hermes.eval.live_vector import StageRunSnapshot
from hermes.tools.models.router import ModelCallAccount, bounded_excerpt

__all__ = [
    "DEFAULT_EXCERPT_BYTES",
    "DEFAULT_MAX_BYTES",
    "NO_EVIDENCE_REASON",
    "build_run_report",
    "new_run_id",
    "redact_report",
    "report_path",
    "write_run_report",
]

REPORT_VERSION = 1
DEFAULT_MAX_BYTES = 1_048_576
DEFAULT_EXCERPT_BYTES = 2_000

DISCLAIMER = (
    "Diagnostic artifact, not a record. This file is never read back as "
    "authority, replayed, or consulted by a validator. The append-only journal "
    "remains the durable record of the run."
)


def new_run_id(started_at: str, project_id: str) -> str:
    """The report's identity, derived from the run start and project.

    A diagnostic id, not a spine identity: the timestamp keeps successive
    reports from overwriting one another, and the sanitized project makes the
    file name readable without accepting path separators.
    """
    stamp = re.sub(r"[^0-9A-Za-z]", "", started_at) or "unknown"
    safe = re.sub(r"[^0-9A-Za-z_.-]", "_", project_id) or "project"
    return f"run_{stamp}_{safe}"


def report_path(run_dir: Path | str, run_id: str) -> Path:
    return Path(run_dir) / f"{run_id}.json"


def build_run_report(
    *,
    run_id: str,
    project_id: str,
    started_at: str,
    ticks: int,
    stage_runs: Sequence[StageRunSnapshot],
    ledger: Sequence[ModelCallAccount],
    notes: Sequence[str],
    vector: str,
    mode: str = "live",
    excerpt_bytes: int = DEFAULT_EXCERPT_BYTES,
    generated_at: str = "",
    task_outcomes: Sequence[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    """Assemble the report from the live run's own surfaces.

    Only the listed fields are copied; prompts, credential state and the
    model's normalized request are never read. A refusal's diagnostic excerpt
    is the *reply* text, bounded here again — carried for model-plane and
    gateway refusals alike (OPS-5K), so a refused ref shows what was written.

    OPS-5L: ``task_outcomes`` is the root methodology task's outcome (its
    final state and the reason on its latest FAILED transition). The report's
    terminal mirrors that record instead of inferring success from stage
    states; ``terminal_reason`` names the failure. When no task outcome is
    supplied, a stage-only report still fails closed if an ``EVIDENCE`` stage
    admitted no ``EVIDENCE_TRANSITION`` anywhere in the run. This is a
    diagnostic field, never an authority: the journal and the task row remain
    the record.
    """
    stages: list[dict[str, Any]] = []
    refusals: list[dict[str, Any]] = []
    for snapshot in stage_runs:
        result = snapshot.result
        stages.append({
            "stage": snapshot.stage,
            "profile": result.profile,
            "task_id": result.task_id,
            "state": result.state,
            "termination": result.termination,
            "proposals": len(result.proposals),
            "admissions": len(result.admitted()),
            "refusals": len(result.refusals),
        })
        for refusal in result.refusals:
            refusals.append({
                "code": refusal.code,
                "detail": refusal.detail,
                "profile": refusal.profile or result.profile,
                "tick": refusal.tick,
                "stage": snapshot.stage,
                "excerpt": bounded_excerpt(refusal.excerpt, excerpt_bytes),
            })

    attempts = [{
        "tier": row.tier,
        "provider": row.provider_id,
        "model": row.model_id,
        "attempt": row.attempt,
        "outcome": row.outcome,
        "tokens_in": row.usage.input_tokens,
        "tokens_out": row.usage.output_tokens,
        "duration_ms": row.duration_ms,
    } for row in ledger]

    note_text = tuple(str(note) for note in notes)
    quarantine = next(
        (note for note in note_text if "quarantin" in note.lower()), "")
    terminal, terminal_reason = _terminal(
        quarantine=quarantine, stage_runs=stage_runs,
        task_outcomes=task_outcomes, excerpt_bytes=excerpt_bytes)

    return {
        "report": "diagnostic-run-report",
        "version": REPORT_VERSION,
        "not_a_record": True,
        "disclaimer": DISCLAIMER,
        "run_id": run_id,
        "project_id": project_id,
        "started_at": started_at,
        "generated_at": generated_at or datetime.now(UTC).isoformat(),
        "mode": mode,
        "ticks": ticks,
        "terminal_state": terminal,
        "terminal_reason": terminal_reason,
        "quarantine_reason": quarantine,
        "stages": stages,
        "model_attempts": attempts,
        "refusals": refusals,
        "notes": list(note_text),
        "vector": vector,
        "truncated": False,
        "stages_omitted": 0,
        "model_attempts_omitted": 0,
        "refusals_omitted": 0,
        "notes_omitted": 0,
    }


#: The fail-closed backstop's reason (OPS-5L). Diagnostic text, not a code: the
#: terminal is the existing ``FAILED``, and this sentence says why.
NO_EVIDENCE_REASON = (
    "the run admitted no EVIDENCE_TRANSITION: an EVIDENCE stage ran, and no "
    "evidence ref was admitted in any stage of the run (OPS-5L)")


def _terminal(
    *,
    quarantine: str,
    stage_runs: Sequence[StageRunSnapshot],
    task_outcomes: Sequence[Mapping[str, Any]],
    excerpt_bytes: int,
) -> tuple[str, str]:
    """The report's terminal and the reason that explains it (OPS-5L).

    Precedence, most authoritative first:

    1. a quarantine note: ``QUARANTINED`` (OPS-10, unchanged), and the note is
       the reason;
    2. a root task that did not end ``SUCCEEDED``: ``FAILED``, and the reason is
       the task's latest FAILED transition reason (or a sentence naming its
       state when none is on file);
    3. an ``EVIDENCE`` stage run with no admitted ``EVIDENCE_TRANSITION`` in any
       stage of the run: ``FAILED`` (the fail-closed backstop, for a caller
       with no task outcome and as a second check when there is one). It reads
       the admitted proposals' *kind*, never the admission count, so a review
       child's ``INSERT_TASK`` cannot mask it;
    4. no stage runs and no task outcome: ``NO_STAGE_RUNS``;
    5. every stage run ``SUCCEEDED``: ``SUCCEEDED``;
    6. otherwise ``FAILED``, naming the first stage run that did not succeed.

    Only existing vocabulary: no terminal value is new. ``SUCCEEDED`` needs
    every check to pass, so the stage data can veto a task outcome but can
    never promote one. The reason is empty exactly when the terminal is
    ``SUCCEEDED`` or ``NO_STAGE_RUNS``.
    """
    succeeded = TaskStatus.SUCCEEDED.value
    if quarantine:
        return "QUARANTINED", bounded_excerpt(quarantine, excerpt_bytes)
    for outcome in task_outcomes:
        state = str(outcome.get("state") or "")
        if state == succeeded:
            continue
        reason = str(outcome.get("reason") or "")
        if not reason:
            task_id = str(outcome.get("task_id") or "")
            reason = (f"root task {task_id!r} ended {state or 'UNKNOWN'} "
                      f"with no FAILED reason on file")
        return "FAILED", bounded_excerpt(reason, excerpt_bytes)
    ran_evidence = any(snapshot.stage == "EVIDENCE" for snapshot in stage_runs)
    admitted_evidence = any(
        proposal.intent.kind == IntentKind.EVIDENCE_TRANSITION
        for snapshot in stage_runs
        for proposal in snapshot.result.admitted())
    if ran_evidence and not admitted_evidence:
        return "FAILED", NO_EVIDENCE_REASON
    if not stage_runs and not task_outcomes:
        return "NO_STAGE_RUNS", ""
    for snapshot in stage_runs:
        result = snapshot.result
        if result.state != succeeded:
            return "FAILED", (
                f"stage {snapshot.stage} ended {result.state}"
                + (f" ({result.termination})" if result.termination else ""))
    return "SUCCEEDED", ""


def redact_report(report: Mapping[str, Any],
                  secrets: Sequence[str]) -> dict[str, Any]:
    """Replace every injected secret with ``<redacted>``, recursively.

    The report never reads the credential itself; this is defence in depth so
    a model reply that echoed a secret cannot carry it into the file.
    """
    values = tuple(secret for secret in secrets if secret)
    redacted = _redact(report, values)
    assert isinstance(redacted, dict)
    return redacted


def _redact(value: Any, secrets: tuple[str, ...]) -> Any:
    if isinstance(value, str):
        for secret in secrets:
            value = value.replace(secret, "<redacted>")
        return value
    if isinstance(value, Mapping):
        return {str(key): _redact(item, secrets)
                for key, item in value.items()}
    if isinstance(value, list):
        return [_redact(item, secrets) for item in value]
    if isinstance(value, tuple):
        return tuple(_redact(item, secrets) for item in value)
    return value


def write_run_report(path: Path | str, report: Mapping[str, Any], *,
                     max_bytes: int = DEFAULT_MAX_BYTES) -> Path:
    """Write a bounded report atomically. Raises on any I/O or size failure."""
    fitted = _fit(copy.deepcopy(dict(report)), max_bytes)
    raw = _encode(fitted)
    if len(raw) > max_bytes:
        raise ValueError(
            f"report is {len(raw)} bytes after truncation, over the "
            f"{max_bytes}-byte cap")
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(target.name + ".tmp")
    try:
        temporary.write_bytes(raw)
        os.replace(temporary, target)
    finally:
        if temporary.exists():
            with contextlib.suppress(OSError):
                temporary.unlink()
    return target


def _encode(report: Mapping[str, Any]) -> bytes:
    return json.dumps(report, indent=2, ensure_ascii=False,
                      default=str).encode("utf-8")


def _fit(report: dict[str, Any], max_bytes: int) -> dict[str, Any]:
    """Truncate counted list bodies until the report fits, or go minimal.

    The order is deliberate: refusals (the largest diagnostic bodies), then
    model attempts, then stages, then notes. Every removed item increments its
    own ``*_omitted`` counter, so a truncated report never silently looks
    complete.
    """
    if len(_encode(report)) <= max_bytes:
        return report
    report["truncated"] = True
    for key, omitted in (("refusals", "refusals_omitted"),
                         ("model_attempts", "model_attempts_omitted"),
                         ("stages", "stages_omitted"),
                         ("notes", "notes_omitted")):
        _trim(report, key, omitted, max_bytes)
    if len(_encode(report)) > max_bytes:
        refusals = report.get("refusals")
        if isinstance(refusals, list):
            for refusal in refusals:
                if isinstance(refusal, dict):
                    refusal["excerpt"] = ""
    if len(_encode(report)) <= max_bytes:
        return report
    minimal_keys = (
        "report", "version", "not_a_record", "disclaimer", "run_id",
        "project_id", "started_at", "generated_at", "mode", "ticks",
        "terminal_state", "terminal_reason", "quarantine_reason", "vector",
        "truncated",
        "stages_omitted", "model_attempts_omitted", "refusals_omitted",
        "notes_omitted")
    minimal = {key: report[key] for key in minimal_keys if key in report}
    minimal["truncated"] = True
    minimal["error"] = "report exceeded max_bytes; list bodies omitted"
    return minimal


def _trim(report: dict[str, Any], key: str, omitted_key: str,
          max_bytes: int) -> None:
    items = report.get(key)
    if not isinstance(items, list) or not items:
        return
    low, high = 0, len(items)
    while low < high:
        middle = (low + high + 1) // 2
        report[key] = items[:middle]
        report[omitted_key] = len(items) - middle
        if len(_encode(report)) <= max_bytes:
            low = middle
        else:
            high = middle - 1
    report[key] = items[:low]
    report[omitted_key] = len(items) - low
