# SPDX-License-Identifier: Apache-2.0
"""Backfill the declared content format, without resurrecting the walls.

OPS-5Z Group C made a read a *state* and a shape a *declaration*: an artifact's
reader dispatches on ``metadata["content_format"]``, which the fetch path writes
from the adapter's ``fetch_content_format(media_type)``. Artifacts fetched
before that change carry no such key, so they read ``fallback`` and the claim
gate caves them — including the 33,727-byte OpenAlex record every live slice has
been measured against.

This is the one-shot migration. It is deliberately *not* a media-type mapper:

1. The candidate format comes from the recorded ``provider`` (first) and the
   recorded ``media_type`` (second), through the same adapter hook the fetch
   path uses. No second mapping table.
2. Before a format is written, ``fetch_content_refusal`` runs over the stored
   bytes with that media type and the recorded HTTP status. If the fetch gate
   refuses the bytes today, the artifact is recorded **not citable**: the
   reserved ``refused`` token is written, and the refusal (code + detail) is
   recorded beside it.
3. Only bytes that pass the gate get a format. The reader may still report
   ``unreadable`` if the declared shape does not parse; that is the reader's
   honest state, never a grant of content.

The principle: **a migration may not grant an artifact a status the system
would refuse it today.** Three of the four live artifacts are PubMed cookie
walls that arrived with HTTP 203. Declaring them ``html`` because their media
type says so would make 153 characters of "Cookies must be enabled" citable
prose. They stay in the database, marked refused — and their ``content_format``
is the reserved ``refused`` token, not an empty string, so the reader calls
them unreadable even if a refused body is plain text.

What is written (all additive; no id, hash, body, size or storage path changes):

    "content_format":            "openalex" | ... | "refused"  <- readers use this
    "content_format_candidate":  what provider+media_type declared
    "content_gate":              {"verdict": "pass"} or
                                 {"verdict": "refused", "code": ..., "detail": ...}
    "content_state":             "content" | "unreadable" | "refused"
    "content_read":              "content" | "unreadable" | "fallback"
    "content_read_detail":       present only when the reader said why
    "content_backfill":          {"schema": "ops-5z/1", provider, media_type,
                                  status, status_source}

A refused row gets the reserved token ``refused`` in ``content_format`` on
purpose. The reader reports that token ``unreadable`` for **every** byte shape —
including plain text, which an empty format would call ``content``. That is the
structural guarantee that a refused 203 body cannot become prose no matter what
it contains. The adjacent keys answer "was this ever a source?" with "no, and
here is why": ``content_state`` is ``refused`` and ``content_gate`` names the
code. A passing row gets the candidate token; ``content_state`` is ``content``
or ``unreadable`` according to the reader, which then says whether the bytes are
actually its shape.

Idempotence: any artifact already carrying ``content_format`` — including the
empty string this migration writes for a refused byte stream — is untouched, so
a second run performs zero writes and says so. The only UPDATE is on
``artifacts.metadata_json``, inside one ``BEGIN IMMEDIATE`` transaction. This
script is outside the runtime import graph and is never called by a run.

Dry-run by default. ``--apply`` performs the write. Usage::

    python scripts/backfill_content_format.py \\
        --db "D:/New folder/hermes-live.db" \\
        --artifacts-root "D:/New folder/hermes-live-artifacts"

    python scripts/backfill_content_format.py ... --apply
"""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path
from typing import Any, Sequence

REPO_ROOT = Path(__file__).resolve().parents[1]
_SRC = REPO_ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from hermes.artifacts.store import compute_content_hash  # noqa: E402
from hermes.persistence.database import (  # noqa: E402
    connect,
    get_schema_version,
)
from hermes.persistence.migrations import SUPPORTED_VERSION  # noqa: E402
from hermes.tools.capabilities.content import (  # noqa: E402
    REFUSED_CONTENT_FORMAT,
    read_content,
)
from hermes.tools.providers.adapters import resolve_adapter  # noqa: E402
from hermes.tools.providers.content import (  # noqa: E402
    ContentRefusal,
    fetch_content_refusal,
)
from hermes.tools.research_sources import ProviderValidationError  # noqa: E402

__all__ = [
    "BACKFILL_SCHEMA",
    "BackfillError",
    "BackfillSummary",
    "RowPlan",
    "format_plan",
    "format_summary",
    "run_backfill",
]

BACKFILL_SCHEMA = "ops-5z/1"

_WRITE = "write"
_RECORDED = "recorded"
_LEFT_ALONE = "left-alone"

_STATUS_CLASS = re.compile(r"HTTP_(\d{3})")
_READ_RANGES = range(100, 600)


class BackfillError(RuntimeError):
    """The migration refused to proceed; nothing was written."""


@dataclass(frozen=True, slots=True)
class RowPlan:
    """One artifact row, measured before any write."""

    artifact_id: str
    project_id: str
    size_bytes: int
    provider: str
    media_type: str
    status: int
    status_source: str
    candidate_format: str
    refusal: ContentRefusal | None
    content_format: str
    gate: dict[str, str]
    content_state: str
    read_state: str
    read_detail: str
    content_chars: int
    action: str
    reason: str
    wrote: bool = False


@dataclass(frozen=True, slots=True)
class BackfillSummary:
    """The run's result: one plan per row, and how many were written."""

    applied: bool
    rows: tuple[RowPlan, ...]
    changed: int

    @property
    def recorded(self) -> int:
        return sum(plan.action == _RECORDED for plan in self.rows)

    @property
    def left_alone(self) -> int:
        return sum(plan.action == _LEFT_ALONE for plan in self.rows)


def _text(value: object) -> str:
    return value.strip() if isinstance(value, str) else ""


def _metadata(row: sqlite3.Row) -> dict[str, Any] | None:
    raw = row["metadata_json"]
    if raw in (None, ""):
        return {}
    try:
        parsed = json.loads(raw)
    except ValueError:
        return None
    return parsed if isinstance(parsed, dict) else None


def _timestamp(value: str) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _milliseconds_apart(left: datetime, right: datetime) -> float | None:
    """Absolute distance, or None when one side is naive and the other aware."""
    try:
        return abs((left - right).total_seconds()) * 1000.0
    except TypeError:
        return None


def _status_from_metadata(metadata: dict[str, Any]) -> tuple[int, str] | None:
    for key in ("status", "http_status", "response_status"):
        value = metadata.get(key)
        if (isinstance(value, int) and not isinstance(value, bool)
                and value in _READ_RANGES):
            return value, f"artifact metadata {key!r}"
    return None


def _recorded_status(
    conn: sqlite3.Connection,
    *,
    content_hash: str,
    metadata: dict[str, Any],
    created_at: str,
) -> tuple[int | None, str]:
    """The HTTP status recorded for these bytes, and where it came from.

    The artifact row does not carry a status. The fetch record does:
    ``provider_interactions.response_body_hash`` is the body's content hash and
    ``response_status_class`` is ``HTTP_<code>``. Rows for the same body are
    matched to the artifact's own ``retrieved_at`` (falling back to its
    ``created_at``) so the status used is the one from the fetch that produced
    the row. If several conflict and no timestamp can anchor one, the result is
    ``(None, reason)`` and the artifact is left alone — a guess here would
    decide citability.

    No status at all is **not** treated as 200. The gate's 203 rule cannot be
    evaluated without the status, and assuming 200 would grant an artifact a
    status the fetch gate might refuse. Such a row is left alone and named.
    """
    from_metadata = _status_from_metadata(metadata)
    if from_metadata is not None:
        return from_metadata
    rows = conn.execute(
        "SELECT response_status_class, retrieved_at "
        "FROM provider_interactions WHERE response_body_hash = ? "
        "ORDER BY retrieved_at, interaction_id",
        (content_hash,),
    ).fetchall()
    statuses: list[tuple[int, str]] = []
    for row in rows:
        match = _STATUS_CLASS.fullmatch(_text(row["response_status_class"]))
        if match is not None:
            statuses.append((int(match.group(1)), _text(row["retrieved_at"])))
    if not statuses:
        return None, (
            "no recorded HTTP status for these bytes; the fetch gate's 203 "
            "rule cannot be evaluated, so the row was left alone rather than "
            "assuming 200")
    distinct = {status for status, _ in statuses}
    if len(distinct) == 1:
        return statuses[0][0], (
            f"provider_interactions ({len(statuses)} row(s), "
            f"HTTP {statuses[0][0]})")
    anchor = _timestamp(_text(metadata.get("retrieved_at"))) or _timestamp(
        created_at)
    if anchor is None:
        return None, (
            "conflicting recorded statuses "
            f"{sorted(distinct)} and no timestamp to anchor the fetch that "
            "produced this row; left alone rather than guessing")
    parsed = [(_timestamp(stamp), status) for status, stamp in statuses]
    scored: list[tuple[float, int]] = []
    for when, status in parsed:
        if when is None:
            continue
        delta = _milliseconds_apart(when, anchor)
        if delta is not None:
            scored.append((delta, status))
    if not scored:
        return None, (
            "conflicting recorded statuses "
            f"{sorted(distinct)} and no comparable timestamps; left alone")
    scored.sort(key=lambda item: item[0])
    delta_ms, status = scored[0]
    if (len(scored) > 1 and abs(scored[1][0] - delta_ms) < 1e-6
            and scored[1][1] != status):
        return None, (
            "conflicting recorded statuses "
            f"{sorted(distinct)} are equally close to the artifact's "
            "retrieved_at; left alone rather than choosing one")
    return status, (
        f"provider_interactions nearest to the artifact's retrieved_at "
        f"(HTTP {status}, Δ {delta_ms:.1f} ms)")


def _stored_bytes(root: Path, row: sqlite3.Row) -> tuple[bytes | None, str]:
    storage = _text(row["storage_path"])
    if not storage:
        return None, "the row has no storage_path; its bytes cannot be checked"
    relative = Path(storage.replace("\\", "/"))
    if relative.is_absolute() or ".." in relative.parts:
        return None, (
            f"storage_path {storage!r} is not a path inside the artifact "
            "store; refusing to read outside the root")
    path = root / relative
    try:
        data = path.read_bytes()
    except OSError as exc:
        return None, f"stored bytes are unreadable at {path}: {exc}"
    digest = compute_content_hash(data)
    if digest != row["content_hash"]:
        return None, (
            f"stored bytes hash {digest[:16]}… do not re-derive the row's "
            f"content hash {row['content_hash'][:16]}…; refusing to describe "
            "bytes the row does not name")
    return data, ""


def _plan(
    *,
    action: str,
    reason: str,
    row: sqlite3.Row,
    provider: str = "",
    media_type: str = "",
    status: int = 0,
    status_source: str = "",
    candidate_format: str = "",
    refusal: ContentRefusal | None = None,
    content_format: str = "",
    gate: dict[str, str] | None = None,
    content_state: str = "",
    read_state: str = "",
    read_detail: str = "",
    content_chars: int = 0,
) -> RowPlan:
    return RowPlan(
        artifact_id=row["artifact_id"],
        project_id=_text(row["project_id"]),
        size_bytes=int(row["size_bytes"]),
        provider=provider,
        media_type=media_type,
        status=status,
        status_source=status_source,
        candidate_format=candidate_format,
        refusal=refusal,
        content_format=content_format,
        gate=dict(gate or {}),
        content_state=content_state,
        read_state=read_state,
        read_detail=read_detail,
        content_chars=content_chars,
        action=action,
        reason=reason,
    )


def plan_row(
    conn: sqlite3.Connection, row: sqlite3.Row, artifact_root: Path,
) -> RowPlan:
    """One row, classified: write / already recorded / left alone.

    Pure apart from the reads: no write happens here. A row is left alone when
    the derivation is ambiguous (no provider, unknown provider, no declared
    format for the media type, no or conflicting recorded status) or when its
    bytes cannot be re-derived. It is never guessed at.
    """
    metadata = _metadata(row)
    if metadata is None:
        return _plan(
            action=_LEFT_ALONE, row=row,
            reason=("metadata_json is not a JSON object; refusing to rewrite "
                    "a record this migration cannot read"))
    if "content_format" in metadata:
        recorded = _text(metadata.get("content_format"))
        return _plan(
            action=_RECORDED, row=row,
            provider=_text(metadata.get("provider")),
            media_type=_text(metadata.get("media_type")),
            candidate_format=_text(metadata.get("content_format_candidate")),
            content_format=recorded,
            read_state=_text(metadata.get("content_read")),
            reason="already carries content_format; untouched")

    provider = _text(metadata.get("provider"))
    media_type = _text(metadata.get("media_type"))
    if not provider:
        return _plan(
            action=_LEFT_ALONE, row=row, media_type=media_type,
            reason=("no provider recorded; a media type alone is not a format "
                    "declaration, so nothing was derived"))
    try:
        adapter = resolve_adapter(provider)()
    except ProviderValidationError as exc:
        return _plan(
            action=_LEFT_ALONE, row=row, provider=provider,
            media_type=media_type,
            reason=f"provider {provider!r} has no adapter: {exc}")
    candidate = _text(adapter.fetch_content_format(media_type or None))
    if not candidate:
        return _plan(
            action=_LEFT_ALONE, row=row, provider=provider,
            media_type=media_type,
            reason=(f"provider {provider!r} declares no content format for "
                    f"media type {media_type!r}; nothing to backfill"))

    raw, bytes_reason = _stored_bytes(artifact_root, row)
    if raw is None:
        return _plan(
            action=_LEFT_ALONE, row=row, provider=provider,
            media_type=media_type, candidate_format=candidate,
            reason=bytes_reason)

    status, status_source = _recorded_status(
        conn, content_hash=row["content_hash"], metadata=metadata,
        created_at=_text(row["created_at"]))
    if status is None:
        return _plan(
            action=_LEFT_ALONE, row=row, provider=provider,
            media_type=media_type, candidate_format=candidate,
            reason=status_source)

    refusal = fetch_content_refusal(
        status=status, media_type=media_type or None, body=raw)
    if refusal is not None:
        read = read_content(raw, format=REFUSED_CONTENT_FORMAT)
        return _plan(
            action=_WRITE, row=row, provider=provider,
            media_type=media_type, status=status,
            status_source=status_source, candidate_format=candidate,
            refusal=refusal, content_format=REFUSED_CONTENT_FORMAT,
            gate={"verdict": "refused", "code": refusal.code,
                  "detail": refusal.detail},
            content_state="refused",
            read_state=read.state.value, read_detail=read.detail,
            content_chars=len(read.text),
            reason=(f"the fetch gate refuses these bytes today "
                    f"({refusal.code}); recorded not citable"))

    read = read_content(raw, format=candidate)
    return _plan(
        action=_WRITE, row=row, provider=provider,
        media_type=media_type, status=status,
        status_source=status_source, candidate_format=candidate,
        content_format=candidate, gate={"verdict": "pass"},
        content_state=read.state.value,
        read_state=read.state.value, read_detail=read.detail,
        content_chars=len(read.text),
        reason=(f"declared {candidate!r}; the reader returns "
                f"{read.state.value}"))


def _updated_metadata(
    metadata: dict[str, Any], plan: RowPlan,
) -> dict[str, Any]:
    """The additive rewrite, with a guard against silent destruction."""
    updated = dict(metadata)
    updated["content_format"] = plan.content_format
    updated["content_format_candidate"] = plan.candidate_format
    updated["content_gate"] = dict(plan.gate)
    updated["content_state"] = plan.content_state
    updated["content_read"] = plan.read_state
    if plan.read_detail:
        updated["content_read_detail"] = plan.read_detail
    updated["content_backfill"] = {
        "schema": BACKFILL_SCHEMA,
        "provider": plan.provider,
        "media_type": plan.media_type,
        "status": plan.status,
        "status_source": plan.status_source,
    }
    for key, value in metadata.items():
        if key not in updated or updated[key] != value:
            raise BackfillError(
                f"refusing to rewrite metadata for {plan.artifact_id}: key "
                f"{key!r} would change")
    return updated


def _select_rows(
    conn: sqlite3.Connection, only: Sequence[str],
) -> list[sqlite3.Row]:
    sql = (
        "SELECT artifact_id, project_id, size_bytes, content_hash, "
        "storage_path, metadata_json, created_at FROM artifacts")
    params: tuple[str, ...] = ()
    if only:
        placeholders = ", ".join("?" for _ in only)
        sql += f" WHERE artifact_id IN ({placeholders})"
        params = tuple(only)
    sql += " ORDER BY artifact_id"
    return list(conn.execute(sql, params).fetchall())


def _plan_all(
    conn: sqlite3.Connection, artifact_root: Path, only: Sequence[str],
) -> tuple[RowPlan, ...]:
    return tuple(
        plan_row(conn, row, artifact_root)
        for row in _select_rows(conn, only))


def run_backfill(
    conn: sqlite3.Connection,
    artifact_root: Path,
    *,
    apply: bool = False,
    only: Sequence[str] = (),
) -> BackfillSummary:
    """Plan every row, and with ``apply`` write the planned metadata."""
    plans = _plan_all(conn, artifact_root, only)
    if not apply:
        return BackfillSummary(
            applied=False, rows=plans,
            changed=sum(plan.action == _WRITE for plan in plans))
    if not any(plan.action == _WRITE for plan in plans):
        return BackfillSummary(applied=True, rows=plans, changed=0)

    conn.execute("BEGIN IMMEDIATE")
    try:
        # Re-plan under the write lock: a row that changed between the dry
        # plan and this transaction is measured as it is now, never as it was.
        plans = _plan_all(conn, artifact_root, only)
        written: list[RowPlan] = []
        for plan in plans:
            if plan.action != _WRITE:
                written.append(plan)
                continue
            row = conn.execute(
                "SELECT metadata_json FROM artifacts WHERE artifact_id = ?",
                (plan.artifact_id,)).fetchone()
            if row is None:
                raise BackfillError(
                    f"{plan.artifact_id}: the row vanished mid-migration")
            metadata = _metadata(row)
            if metadata is None:
                raise BackfillError(
                    f"{plan.artifact_id}: metadata became unreadable "
                    "mid-migration")
            updated = _updated_metadata(metadata, plan)
            new_json = json.dumps(
                updated, sort_keys=True, ensure_ascii=False)
            cursor = conn.execute(
                "UPDATE artifacts SET metadata_json = ? "
                "WHERE artifact_id = ? AND metadata_json = ?",
                (new_json, plan.artifact_id, row["metadata_json"]))
            if cursor.rowcount != 1:
                raise BackfillError(
                    f"{plan.artifact_id}: metadata changed between the plan "
                    "and the update; nothing was committed")
            written.append(replace(plan, wrote=True))
        conn.execute("COMMIT")
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    return BackfillSummary(
        applied=True, rows=tuple(written),
        changed=sum(plan.wrote for plan in written))


def _gate_label(plan: RowPlan) -> str:
    if plan.action == _RECORDED:
        return "ALREADY-RECORDED"
    if plan.action == _LEFT_ALONE:
        return "NOT-RUN"
    verdict = plan.gate.get("verdict", "")
    if verdict == "pass":
        return "PASS"
    if verdict == "refused":
        return f"REFUSED {plan.gate.get('code', '')}".strip()
    return "NOT-RUN"


def _final_label(plan: RowPlan) -> str:
    if plan.action == _RECORDED:
        return f"untouched (content_format={plan.content_format!r})"
    if plan.action == _LEFT_ALONE:
        return f"left-alone (reads fallback): {plan.reason}"
    if plan.refusal is not None:
        return (f"refused (not citable; content_format="
                f"{REFUSED_CONTENT_FORMAT!r})")
    if plan.read_state == "content":
        label = f"content ({plan.content_chars} chars)"
        return f"{label}; {plan.read_detail}" if plan.read_detail else label
    if plan.read_detail:
        return f"{plan.read_state} ({plan.read_detail})"
    return plan.read_state


def format_plan(plan: RowPlan) -> str:
    """The per-row audit line: artifact, size, derived format, gate, state."""
    candidate = plan.candidate_format or "-"
    provider = plan.provider or "-"
    media = plan.media_type or "-"
    status = str(plan.status) if plan.status else "-"
    return (
        f"{plan.artifact_id[:8]}  {plan.project_id:<14} "
        f"{plan.size_bytes:>7}B  provider={provider:<10} media={media:<18} "
        f"status={status:<4} candidate={candidate:<9} "
        f"gate={_gate_label(plan):<34} final={_final_label(plan)}")


def format_summary(summary: BackfillSummary) -> str:
    rows = len(summary.rows)
    if not summary.applied:
        if summary.changed == 0:
            return (f"dry-run: {rows} row(s); 0 would change; "
                    f"{summary.recorded} already carry content_format, "
                    f"{summary.left_alone} left alone — nothing to do")
        return (f"dry-run: {rows} row(s); {summary.changed} would change; "
                "re-run with --apply to write")
    if summary.changed == 0:
        return (f"applied: {rows} row(s); 0 changed; {summary.recorded} "
                f"already carry content_format, {summary.left_alone} left "
                "alone — nothing to do")
    return (f"applied: {rows} row(s); {summary.changed} changed; "
            f"{summary.recorded} already recorded, "
            f"{summary.left_alone} left alone")


def _connect_readonly(path: Path) -> sqlite3.Connection:
    uri = "file:" + path.resolve().as_posix() + "?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def _summary_json(summary: BackfillSummary) -> dict[str, Any]:
    return {
        "applied": summary.applied,
        "changed": summary.changed,
        "rows": [
            {
                "artifact_id": plan.artifact_id,
                "project_id": plan.project_id,
                "size_bytes": plan.size_bytes,
                "provider": plan.provider,
                "media_type": plan.media_type,
                "status": plan.status,
                "status_source": plan.status_source,
                "candidate_format": plan.candidate_format,
                "gate": plan.gate,
                "content_format": plan.content_format,
                "content_state": plan.content_state,
                "read": plan.read_state,
                "read_detail": plan.read_detail,
                "content_chars": plan.content_chars,
                "action": plan.action,
                "reason": plan.reason,
                "wrote": plan.wrote,
            }
            for plan in summary.rows
        ],
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--db", type=Path, required=True,
                        help="path to the Hermes journal to migrate")
    parser.add_argument("--artifacts-root", type=Path, required=True,
                        help="root of the content-addressed artifact store")
    parser.add_argument("--apply", action="store_true",
                        help="write the metadata; without it, dry-run only")
    parser.add_argument("--only", action="append", default=[],
                        help="restrict to one artifact id (repeatable)")
    parser.add_argument("--json", action="store_true",
                        help="print the plan as JSON instead of lines")
    args = parser.parse_args(argv)

    if not args.db.exists():
        print(f"refused: database not found: {args.db}", file=sys.stderr)
        return 2
    if not args.artifacts_root.is_dir():
        print(f"refused: artifact root not found: {args.artifacts_root}",
              file=sys.stderr)
        return 2

    conn = connect(args.db) if args.apply else _connect_readonly(args.db)
    try:
        version = get_schema_version(conn)
        if version != SUPPORTED_VERSION:
            print(
                f"refused: {args.db} is schema {version}, this build supports "
                f"{SUPPORTED_VERSION}; run the schema migrations first",
                file=sys.stderr)
            return 2
        if args.only:
            present = {row["artifact_id"] for row in conn.execute(
                "SELECT artifact_id FROM artifacts")}
            missing = [item for item in args.only if item not in present]
            if missing:
                print(
                    f"refused: --only id(s) not in {args.db}: "
                    f"{', '.join(missing)}", file=sys.stderr)
                return 2
        summary = run_backfill(
            conn, args.artifacts_root, apply=args.apply, only=args.only)
    finally:
        conn.close()

    if args.json:
        print(json.dumps(_summary_json(summary), indent=2, ensure_ascii=False))
    else:
        for plan in summary.rows:
            print(format_plan(plan))
        print(format_summary(summary))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
