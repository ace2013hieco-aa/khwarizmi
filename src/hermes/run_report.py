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
from hermes.eval.live_vector import StageRunSnapshot
from hermes.tools.models.router import ModelCallAccount, bounded_excerpt

__all__ = [
    "DEFAULT_EXCERPT_BYTES",
    "DEFAULT_MAX_BYTES",
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
) -> dict[str, Any]:
    """Assemble the report from the live run's own surfaces.

    Only the listed fields are copied; prompts, credential state and the
    model's normalized request are never read. A refusal's diagnostic excerpt
    is the *reply* text, bounded here again — carried for model-plane and
    gateway refusals alike (OPS-5K), so a refused ref shows what was written.
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
    states = [snapshot.result.state for snapshot in stage_runs]
    if quarantine:
        # A quarantined task outranks per-stage state: its stages may each have
        # ended SUCCEEDED with zero admissions, but the run did not.
        terminal = "QUARANTINED"
    elif not states:
        terminal = "NO_STAGE_RUNS"
    elif all(state == TaskStatus.SUCCEEDED.value for state in states):
        terminal = "SUCCEEDED"
    else:
        terminal = "FAILED"

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
        "terminal_state", "quarantine_reason", "vector", "truncated",
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
