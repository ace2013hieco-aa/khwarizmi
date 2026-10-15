"""CLI boundary (foundation decision §7).

Operational surface only; no business logic (foundation §7). All business
logic lives in Hermes modules. Phase 0 implemented `doctor`. Phase 1 adds
`init`, `status`, `audit`, `project` (create/show), `task` (show), `events`.

The CLI uses the same domain/repository APIs as every other caller (Phase 1
req §23). No duplicate state logic in CLI handlers.
"""
from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
import sys
import uuid
from dataclasses import asdict
from pathlib import Path
from typing import Literal

from . import __version__
from .config import (
    ConfigError,
    HermesConfig,
    config_to_string,
    default_config,
    load_config,
)
from .output import emit, emit_lines, run_boundary

CHECK_STATUS = Literal["AVAILABLE", "OPTIONAL / NOT CONFIGURED", "REQUIRED / MISSING"]


def _status_line(label: str, status: CHECK_STATUS, detail: str = "") -> str:
    pad = "." * max(2, 38 - len(label))
    suffix = f" — {detail}" if detail else ""
    return f"  {label}{pad}[{status}]{suffix}"


def _doctor(args, cfg: HermesConfig | None) -> int:
    """Run `hermes doctor` — probe environment capabilities and report.

    ``--json`` emits ONE JSON document on stdout with a stable schema:
    ``{"version": ..., "checks": [{"label", "status", "detail"}],
    "config": {...}}`` — the same probes as the human table in the same
    order; ``config`` is the resolved configuration as nested sections.
    """
    checks: list[tuple[str, CHECK_STATUS, str]] = []

    py_version = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    if sys.version_info >= (3, 14):
        checks.append(("Python runtime", "AVAILABLE", py_version))
    else:
        checks.append(("Python runtime", "REQUIRED / MISSING", f"{py_version} (need >=3.14)"))

    from importlib.metadata import PackageNotFoundError
    from importlib.metadata import version as pkg_version
    try:
        v = pkg_version("khwarizmi-research")
        checks.append(("Hermes package", "AVAILABLE", f"v{v}"))
    except PackageNotFoundError:
        checks.append(("Hermes package", "AVAILABLE", f"v{__version__} (dev)"))

    if cfg is not None:
        checks.append(("Config file", "AVAILABLE", "loaded"))
    else:
        checks.append(("Config file", "OPTIONAL / NOT CONFIGURED", "using defaults"))

    if cfg is None:
        cfg = default_config()

    from .persistence.database import connect, get_schema_version, integrity_check

    db_path = Path(cfg.sqlite.database_path)
    if db_path.exists():
        try:
            conn = connect(str(db_path))
            version = get_schema_version(conn)
            ok = integrity_check(conn)
            conn.close()
            status: CHECK_STATUS = "AVAILABLE" if ok else "REQUIRED / MISSING"
            checks.append(("Database", status, f"{db_path} (schema v{version})"))
        except sqlite3.DatabaseError as e:
            checks.append(("Database", "REQUIRED / MISSING", str(e)))
    else:
        checks.append(("Database", "OPTIONAL / NOT CONFIGURED", f"{db_path} (run `hermes init`)"))

    artifact_root = Path(cfg.artifacts.artifact_root)
    if artifact_root.exists():
        checks.append(("Artifact store", "AVAILABLE", str(artifact_root)))
    else:
        checks.append(("Artifact store", "OPTIONAL / NOT CONFIGURED", str(artifact_root)))

    if not cfg.sandbox.enabled or not cfg.sandbox.runner:
        checks.append(("Sandbox", "OPTIONAL / NOT CONFIGURED", "disabled in config"))
    else:
        runner_path = shutil.which(cfg.sandbox.runner)
        if runner_path:
            checks.append(("Sandbox", "AVAILABLE", f"{cfg.sandbox.runner} -> {runner_path}"))
        else:
            checks.append(("Sandbox", "OPTIONAL / NOT CONFIGURED", f"{cfg.sandbox.runner} not found"))

    lockfile = Path("uv.lock")
    if lockfile.exists():
        checks.append(("Lockfile", "AVAILABLE", "uv.lock"))
    else:
        checks.append(("Lockfile", "REQUIRED / MISSING", "uv.lock not found"))

    if getattr(args, "as_json", False):
        doc = {
            "version": __version__,
            "checks": [
                {"label": label, "status": status, "detail": detail}
                for label, status, detail in checks
            ],
            "config": asdict(cfg),
        }
        emit_lines(json.dumps(doc, indent=2, sort_keys=True).split("\n"))
        return 0

    lines: list[str] = [f"Hermes doctor — v{__version__}", "=" * 60]
    lines.extend(_status_line(label, status, detail)
                 for label, status, detail in checks[:3])
    lines.append("  ---")
    lines.append("  Configuration values:")
    lines.extend(config_to_string(cfg).split("\n"))
    lines.extend(_status_line(label, status, detail)
                 for label, status, detail in checks[3:])
    lines.append("=" * 60)
    emit_lines(lines)
    return 0


def _init(args, cfg: HermesConfig) -> int:
    """Initialize the Hermes database and artifact store."""
    from .persistence.database import connect
    from .persistence.migrations import migrate_to_latest

    db_path = Path(cfg.sqlite.database_path)
    artifact_root = Path(cfg.artifacts.artifact_root)

    # Create artifact root
    artifact_root.mkdir(parents=True, exist_ok=True)

    # Create and migrate database
    conn = connect(str(db_path))
    version = migrate_to_latest(conn)
    conn.close()

    emit(f"Initialized Hermes database: {db_path} (schema v{version})")
    emit(f"Initialized artifact store:  {artifact_root}")
    return 0


def _status(args, cfg: HermesConfig) -> int:
    """Show project and task status from the persisted database.

    ``--json`` emits ONE JSON document on stdout with a stable schema:
    ``{"projects": [{"project_id", "name", "lifecycle_state",
    "operational_mode", "iteration", "tasks": [{"task_id", "task_type",
    "status", "iteration"}]}]}`` — full ids (the human table truncates to
    8 chars); an empty project set is ``{"projects": []}``. Errors go to
    stderr so stdout stays parseable.
    """
    from .persistence.database import connect
    from .persistence.repositories import ProjectRepository, TaskRepository

    db_path = Path(cfg.sqlite.database_path)
    if not db_path.exists():
        if getattr(args, "as_json", False):
            emit("No database found. Run `hermes init` first.",
                  file=sys.stderr)
        else:
            emit("No database found. Run `hermes init` first.")
        return 1

    conn = connect(str(db_path))
    proj_repo = ProjectRepository(conn)
    task_repo = TaskRepository(conn)

    projects = proj_repo.list_all()

    if getattr(args, "as_json", False):
        doc = {
            "projects": [
                {
                    "project_id": p["project_id"],
                    "name": p["name"],
                    "lifecycle_state": p["lifecycle_state"],
                    "operational_mode": p["operational_mode"],
                    "iteration": p["iteration"],
                    "tasks": [
                        {
                            "task_id": t["task_id"],
                            "task_type": t["task_type"],
                            "status": t["status"],
                            "iteration": t["iteration"],
                        }
                        for t in task_repo.list_for_project(p["project_id"])
                    ],
                }
                for p in projects
            ]
        }
        conn.close()
        emit_lines(json.dumps(doc, indent=2, sort_keys=True).split("\n"))
        return 0

    if not projects:
        emit("No projects found.")
        conn.close()
        return 0

    for p in projects:
        emit(f"  Project: {p['name']} ({p['project_id'][:8]}...)")
        emit(f"    Lifecycle: {p['lifecycle_state']}")
        emit(f"    Mode:      {p['operational_mode']}")
        emit(f"    Iteration: {p['iteration']}")

        tasks = task_repo.list_for_project(p["project_id"])
        if tasks:
            emit(f"    Tasks ({len(tasks)}):")
            for t in tasks:
                emit(f"      {t['task_id'][:8]}... {t['task_type']:12s} {t['status']:14s} (iter {t['iteration']})")
        emit("")

    conn.close()
    return 0
def _audit(args, cfg: HermesConfig) -> int:
    """Print the event journal (audit trail) for a project.

    ``--json`` emits ONE JSON document on stdout (a stable machine-readable
    schema: ``{"events": [{...}]}`` — one object per event row, keys are
    exactly the events-table columns (sorted for stability). ``payload_json`` and
    ``artifact_ids_json`` are parsed to JSON values when valid (the event
    validation guarantees this; NULL -> null), with a raw-string fallback
    for corrupt storage so the read never crashes. Errors go to stderr so
    stdout stays parseable.
    """
    from .persistence.database import connect
    from .persistence.repositories import EventRepository

    db_path = Path(cfg.sqlite.database_path)
    if not db_path.exists():
        emit("No database found. Run `hermes init` first.",
              file=sys.stderr)
        return 1

    project_id = getattr(args, "project_id", None)
    conn = connect(str(db_path))
    event_repo = EventRepository(conn)

    if project_id:
        events = event_repo.list_for_project(project_id)
    else:
        events = event_repo.list_all()

    if getattr(args, "as_json", False):
        def _parse(raw: str | None):
            if raw is None:
                return None
            try:
                return json.loads(raw)
            except (ValueError, TypeError):
                return raw  # corrupt storage — keep the raw string, never crash
        payload = []
        for e in events:
            row = dict(e)
            if row.get("payload_json") is not None:
                row["payload_json"] = _parse(row["payload_json"])
            if row.get("artifact_ids_json") is not None:
                row["artifact_ids_json"] = _parse(row["artifact_ids_json"])
            payload.append(row)
        emit_lines(
            json.dumps({"events": payload}, indent=2, sort_keys=True).split("\n"))
        conn.close()
        return 0

    if not events:
        emit("No events recorded.")
        conn.close()
        return 0

    emit(f"Event journal ({len(events)} events):")
    emit("-" * 80)
    for e in events:
        emit(f"  #{e['event_id']:4d} | {e['event_type']:30s} | proj={e['project_id'] or '-':12s} | task={e['task_id'] or '-':12s}")
        if e["from_state"] or e["to_state"]:
            emit(f"         {e['from_state'] or '-':14s} -> {e['to_state'] or '-':14s}")
        if e["reason"]:
            emit(f"         reason: {e['reason']}")
    emit("-" * 80)
    conn.close()
    return 0


def _project_create(args, cfg: HermesConfig) -> int:
    """Create a new project."""
    from .persistence.database import connect
    from .persistence.migrations import migrate_to_latest
    from .persistence.repositories import ProjectRepository

    db_path = Path(cfg.sqlite.database_path)
    conn = connect(str(db_path))
    migrate_to_latest(conn)

    project_id = str(uuid.uuid4())
    repo = ProjectRepository(conn)
    project = repo.create(project_id, args.name)
    conn.close()

    emit(f"Created project: {project['name']} (id: {project_id})")
    emit(f"  Lifecycle: {project['lifecycle_state']}")
    emit(f"  Mode:      {project['operational_mode']}")
    return 0


def _project_show(args, cfg: HermesConfig) -> int:
    """Show project details."""
    from .persistence.database import connect
    from .persistence.repositories import ProjectRepository, TaskRepository

    db_path = Path(cfg.sqlite.database_path)
    if not db_path.exists():
        emit("No database found. Run `hermes init` first.")
        return 1

    conn = connect(str(db_path))
    proj_repo = ProjectRepository(conn)

    try:
        project = proj_repo.get(args.project_id)
    except Exception as e:  # noqa: BLE001 — CLI boundary reports, never crashes
        emit(f"Error: {e}")
        conn.close()
        return 1

    emit(f"Project: {project['name']}")
    emit(f"  ID:          {project['project_id']}")
    emit(f"  Lifecycle:   {project['lifecycle_state']}")
    emit(f"  Mode:        {project['operational_mode']}")
    emit(f"  Iteration:   {project['iteration']}")
    emit(f"  Created:     {project['created_at']}")
    emit(f"  Updated:     {project['updated_at']}")

    task_repo = TaskRepository(conn)
    tasks = task_repo.list_for_project(args.project_id)
    emit(f"  Tasks: {len(tasks)}")
    for t in tasks:
        emit(f"    {t['task_id'][:8]}... {t['task_type']:12s} {t['status']:14s}")

    conn.close()
    return 0


def _task_show(args, cfg: HermesConfig) -> int:
    """Show task details."""
    from .persistence.database import connect
    from .persistence.repositories import TaskRepository

    db_path = Path(cfg.sqlite.database_path)
    if not db_path.exists():
        emit("No database found. Run `hermes init` first.")
        return 1

    conn = connect(str(db_path))
    task_repo = TaskRepository(conn)

    try:
        task = task_repo.get(args.task_id)
    except Exception as e:  # noqa: BLE001 — CLI boundary reports, never crashes
        emit(f"Error: {e}")
        conn.close()
        return 1

    emit(f"Task: {task['task_id']}")
    emit(f"  Type:        {task['task_type']}")
    emit(f"  Status:      {task['status']}")
    emit(f"  Attempt:     {task['attempt']}")
    emit(f"  Iteration:   {task['iteration']}")
    emit(f"  Idempotency: {task['idempotency_key'][:16]}...")
    if task.get("dependencies"):
        emit(f"  Deps:        {task['dependencies']}")
    if task.get("started_at"):
        emit(f"  Started:     {task['started_at']}")
    if task.get("completed_at"):
        emit(f"  Completed:   {task['completed_at']}")

    conn.close()
    return 0


def _events(args, cfg: HermesConfig) -> int:
    """Show events for a project or all events."""
    from .persistence.database import connect
    from .persistence.repositories import EventRepository

    db_path = Path(cfg.sqlite.database_path)
    if not db_path.exists():
        emit("No database found. Run `hermes init` first.")
        return 1

    conn = connect(str(db_path))
    event_repo = EventRepository(conn)

    project_id = getattr(args, "project_id", None)
    if project_id:
        events = event_repo.list_for_project(project_id)
    else:
        events = event_repo.list_all()

    if not events:
        emit("No events.")
        conn.close()
        return 0

    for e in events:
        emit(f"  #{e['event_id']:4d} | {e['event_type']:30s} | {e['from_state'] or '-':14s} -> {e['to_state'] or '-':14s} | {e['created_at']}")

    conn.close()
    return 0


def _pause(args, cfg: HermesConfig) -> int:
    """Pause the active project."""
    from .core.modes import OperationalMode
    from .persistence.database import connect
    from .persistence.repositories import ProjectRepository

    db_path = Path(cfg.sqlite.database_path)
    if not db_path.exists():
        emit("No database found.")
        return 1

    conn = connect(str(db_path))
    repo = ProjectRepository(conn)
    try:
        project = repo.transition_mode(args.project_id, OperationalMode.PAUSED, caused_by="operator")
        emit(f"Paused: {project['name']} (mode: {project['operational_mode']})")
    except Exception as e:  # noqa: BLE001 — CLI boundary reports, never crashes
        emit(f"Error: {e}")
        conn.close()
        return 1
    conn.close()
    return 0


def _resume(args, cfg: HermesConfig) -> int:
    """Resume a paused project."""
    from .core.modes import OperationalMode
    from .persistence.database import connect
    from .persistence.repositories import ProjectRepository

    db_path = Path(cfg.sqlite.database_path)
    if not db_path.exists():
        emit("No database found.")
        return 1

    conn = connect(str(db_path))
    repo = ProjectRepository(conn)
    try:
        project = repo.transition_mode(args.project_id, OperationalMode.ACTIVE, caused_by="operator")
        emit(f"Resumed: {project['name']} (mode: {project['operational_mode']})")
    except Exception as e:  # noqa: BLE001 — CLI boundary reports, never crashes
        emit(f"Error: {e}")
        conn.close()
        return 1
    conn.close()
    return 0


def _run(args, cfg: HermesConfig) -> int:
    """Drive the REAL controller tick loop through the CLI (red-team A1):
    `hermes run <project_id> [--ticks N]` connects to the configured DB,
    migrates to the latest schema, and drains eligible work via
    Controller.run — the exact machinery the reconciliation tests exercise,
    now reachable from the operator surface. No model/handler injections
    exist at the CLI boundary, so execution is fail-closed by design:
    EXTRACT tasks are left with a diagnostic (extract_fn is None), GATE
    tasks are left unhandled, and HUMAN_GATE tasks park at WAITING_HUMAN —
    surfaced in the summary — until an operator verdict lands through the
    controller's resolve_human_gate surface.

    R-3: the operator knobs are read HERE — the ``[autonomy_caps]`` section
    of the loaded config is handed to the controller, which builds the
    deterministic envelopes (dispatch deadline, step/token budgets, retry
    caps, loop threshold) through the narrow-only builders. A tightened
    value applies; a value above the code-owned ceiling is refused loudly
    (``KNOB_WIDEN_REFUSED``), never silently clamped; an absent section
    carries the code-owned defaults byte-identically.
    """
    from .persistence.database import connect
    from .persistence.migrations import migrate_to_latest
    from .research.controller import Controller

    db_path = Path(cfg.sqlite.database_path)
    if not db_path.exists():
        emit("No database found. Run `hermes init` first.")
        return 1

    conn = connect(str(db_path))
    try:
        migrate_to_latest(conn)
        ctrl = Controller(
            conn, project_id=args.project_id,
            autonomy_operator=cfg.autonomy_caps)
        outcomes = ctrl.run(max_ticks=args.ticks)
        notes = list(ctrl.notes)
    except Exception as e:  # noqa: BLE001 — CLI boundary reports, never crashes
        emit(f"Error: {e}")
        return 1
    finally:
        conn.close()

    def _sum(attr):
        return sum(len(getattr(o, attr)) for o in outcomes)

    emit(
        f"Ran {len(outcomes)} tick(s) for project {args.project_id}: "
        f"{_sum('dispatched')} dispatched, {_sum('succeeded')} succeeded, "
        f"{_sum('waiting_human')} waiting on human, {_sum('failed')} failed, "
        f"{_sum('unhandled')} unhandled."
    )
    for n in notes:
        emit(f"  note: {n}")
    return 0


def _backup(args, cfg: HermesConfig) -> int:
    """`hermes backup` — snapshot the DB (Online Backup API) AND the
    artifact store into the configured backup dir, then retain the last N
    (config). The store snapshot rides with the DB so a later restore
    brings both back to the SAME point (B6)."""
    from .persistence.backup import create_backup, retain_last_n
    from .persistence.database import connect

    db_path = Path(cfg.sqlite.database_path)
    if not db_path.exists():
        emit("No database found. Run `hermes init` first.")
        return 1
    if cfg.sqlite.retain_last_n < 1:
        # B4 — retain 0 would delete the backup we are about to write:
        # refuse loudly instead of printing "Backup written" for a deleted file.
        emit(f"Error: sqlite.retain_last_n must be >= 1, "
              f"got {cfg.sqlite.retain_last_n}")
        return 1

    conn = connect(str(db_path))
    try:
        result = create_backup(
            conn, cfg.sqlite.backup_dir,
            artifact_root=cfg.artifacts.artifact_root)
        retain_last_n(cfg.sqlite.backup_dir, cfg.sqlite.retain_last_n)
    except Exception as e:  # noqa: BLE001 — CLI boundary reports
        emit(f"Error: {e}")
        return 1
    finally:
        conn.close()
    emit(f"Backup written: {result.backup_path}")
    if result.artifact_store_path:
        emit(f"  artifact store snapshot: {result.artifact_store_path}")
    return 0


def _restore(args, cfg: HermesConfig) -> int:
    """`hermes restore <backup_path>` — atomic restore (B6): the backup
    swaps in via temp + rename, -wal/-shm are cleared, integrity is
    verified, and the artifact-store snapshot (when the backup took one)
    is merged back into the live store. All connections are closed before
    the swap."""
    from .persistence.backup import restore_backup

    db_path = Path(cfg.sqlite.database_path)
    backup_path = Path(args.backup_path)
    if not backup_path.exists():
        emit(f"Backup not found: {backup_path}")
        return 1
    if not db_path.exists():
        emit(f"No live database at {db_path} — nothing to restore onto.")
        return 1

    try:
        restore_backup(
            backup_path, db_path,
            live_artifact_root=cfg.artifacts.artifact_root)
    except Exception as e:  # noqa: BLE001 — CLI boundary reports
        emit(f"Error: {e}")
        return 1
    emit(f"Restored {backup_path} onto {db_path} "
          f"(schema migrated on next open).")
    return 0


def _gate_resolve(args, cfg: HermesConfig) -> int:
    """`hermes gate resolve <task_id> --verdict APPROVED|REJECTED
    --operator <id> --token <token>` — land a ratified operator verdict on
    a parked HUMAN_GATE through the controller (A2 + A4), so operators
    never need a Python session. The credential is verified against the
    stored operator-credential hash; an unratified verdict is refused
    fail-closed."""
    from .persistence.database import connect
    from .persistence.migrations import migrate_to_latest
    from .persistence.repositories import NotFoundError, TaskRepository
    from .research.controller import Controller

    db_path = Path(cfg.sqlite.database_path)
    if not db_path.exists():
        emit("No database found. Run `hermes init` first.")
        return 1

    conn = connect(str(db_path))
    try:
        migrate_to_latest(conn)
        project_id = getattr(args, "project_id", None)
        if not project_id:
            try:
                project_id = TaskRepository(conn).get(args.task_id)[
                    "project_id"]
            except NotFoundError:
                emit(f"Error: task {args.task_id!r} not found.")
                return 1
        out = Controller(conn, project_id=project_id).resolve_human_gate(
            task_id=args.task_id, verdict=args.verdict,
            operator_id=args.operator, operator_token=args.token)
    except Exception as e:  # noqa: BLE001 — CLI boundary reports
        emit(f"Error: {e}")
        return 1
    finally:
        conn.close()

    if out["rejected"]:
        detail = out.get("detail") or ""
        emit(f"Refused ({out.get('code')}): {detail}".rstrip())
        return 1
    emit(f"Gate {args.task_id} resolved: {args.verdict} "
          f"(operator {args.operator}).")
    return 0


def _operator_register(args, cfg: HermesConfig) -> int:
    """`hermes operator register <operator_id> --token <token> [--name]` —
    the bootstrap surface for the ratified operator credential (A4). Only
    a salted PBKDF2-HMAC-SHA256 hash of the token is persisted (minimum
    token length enforced at register)."""
    from .persistence.database import connect
    from .persistence.migrations import migrate_to_latest
    from .persistence.repositories import OperatorCredentialRepository

    db_path = Path(cfg.sqlite.database_path)
    if not db_path.exists():
        emit("No database found. Run `hermes init` first.")
        return 1

    conn = connect(str(db_path))
    try:
        migrate_to_latest(conn)
        row = OperatorCredentialRepository(conn).register(
            args.operator_id, args.token, args.name or "")
    except ValueError as e:
        emit(f"Refused (OPERATOR): {e}")
        return 1
    finally:
        conn.close()

    emit(f"Registered operator {row['operator_id']} "
          f"({row['name'] or 'unnamed'}).")
    return 0


def _vault_project(args, cfg: HermesConfig) -> int:
    """Project the journal into the vault notes + the derived-view manifest.

    Operator surface for the P-AUTO-5 projector: reads the persisted cursor
    (0 when absent — full projection), writes the window notes and the
    manifest, then persists the new cursor. The journal is read-only.
    """
    from .persistence.database import connect
    from .persistence.migrations import migrate_to_latest
    from .vault.projection import (
        ProjectionRefused,
        project,
        read_cursor,
        write_cursor,
    )

    db_path = Path(cfg.sqlite.database_path)
    if not db_path.exists():
        emit("No database found. Run `hermes init` first.")
        return 1
    conn = connect(str(db_path))
    try:
        migrate_to_latest(conn)
        cursor = read_cursor(args.vault_root)
        new_cursor, written = project(conn, args.project_id, args.vault_root,
                                      cursor=cursor)
        write_cursor(args.vault_root, new_cursor)
    except ProjectionRefused as exc:
        emit(f"Refused [{exc.code}]: {exc.detail}")
        return 1
    finally:
        conn.close()
    emit(f"Projected {args.project_id} into {args.vault_root}: cursor "
          f"{cursor} -> {new_cursor}, {len(written)} note(s) written; "
          "manifest .projection-manifest.json written.")
    return 0


def _vault_verify(args, cfg: HermesConfig) -> int:
    """Recompute the manifest from the journal and refuse on any mismatch.

    The verifier never trusts the manifest file: it recomputes the claim
    with the projector's planner and names every missing/invented ID. Exit
    1 (with the findings) when the derived view is refused.
    """
    from .persistence.database import connect
    from .vault.manifest import verify_manifest
    from .vault.projection import ProjectionRefused

    db_path = Path(cfg.sqlite.database_path)
    if not db_path.exists():
        emit("No database found. Run `hermes init` first.")
        return 1
    conn = connect(str(db_path))
    try:
        report = verify_manifest(conn, args.project_id, args.vault_root)
    except ProjectionRefused as exc:
        emit(f"Refused [{exc.code}]: {exc.detail}")
        return 1
    finally:
        conn.close()
    if getattr(args, "as_json", False):
        emit_lines(
            json.dumps(report.to_dict(), indent=2, sort_keys=True).split("\n"))
    else:
        for line in report.lines():
            emit(line)
    if not report.ok:
        emit("Vault manifest does not match the journal — the derived view "
              "is refused.", file=sys.stderr)
        return 1
    return 0


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="hermes",
        description=(
            "Hermes Autonomous Quantitative Research Laboratory — "
            "reconciliation loop over a typed research state machine."
        ),
    )
    p.add_argument("--config", type=Path, default=None, help="Path to hermes.toml")
    sub = p.add_subparsers(dest="command")

    sub.add_parser("init", help="Initialize the Hermes database and artifact store.")
    doctor_p = sub.add_parser("doctor", help="Probe environment and report capability status.")
    doctor_p.add_argument("--json", dest="as_json", action="store_true",
                          help="Emit probes as one JSON document on stdout "
                               "(stable schema: {\"version\", \"checks\": "
                               "[{label, status, detail}], \"config\": {...}})")
    sub.add_parser("backup", help="Snapshot the DB + artifact store (B6).")
    restore_p = sub.add_parser("restore", help="Restore a backup atomically (B6).")
    restore_p.add_argument("backup_path")
    status_p = sub.add_parser("status", help="Show project and task status.")
    status_p.add_argument("--json", dest="as_json", action="store_true",
                          help="Emit status as one JSON document on stdout "
                               "(stable schema: {\"projects\": [{...}]}; "
                               "errors go to stderr)")

    audit_p = sub.add_parser("audit", help="Print the event journal (audit trail).")
    audit_p.add_argument("--project", dest="project_id", default=None, help="Filter by project ID.")
    audit_p.add_argument("--json", dest="as_json", action="store_true",
                         help="Emit the ledger as one JSON document on stdout "
                              "(stable schema: {\"events\": [{...row...}]}; "
                              "payload_json/artifact_ids_json are parsed to "
                              "values when valid — NULL -> null, corrupt "
                              "storage -> raw string; errors go to stderr)")

    proj_p = sub.add_parser("project", help="Project lifecycle management.")
    proj_sub = proj_p.add_subparsers(dest="project_command")
    proj_create = proj_sub.add_parser("create", help="Create a new project.")
    proj_create.add_argument("name", help="Project name.")
    proj_show = proj_sub.add_parser("show", help="Show project details.")
    proj_show.add_argument("project_id", help="Project UUID.")

    task_p = sub.add_parser("task", help="Task operations.")
    task_sub = task_p.add_subparsers(dest="task_command")
    task_show = task_sub.add_parser("show", help="Show task details.")
    task_show.add_argument("task_id", help="Task UUID.")

    events_p = sub.add_parser("events", help="Show events from the journal.")
    events_p.add_argument("--project", dest="project_id", default=None, help="Filter by project ID.")

    run_p = sub.add_parser("run", help="Run the reconciliation loop (Phase 3+).")
    run_p.add_argument("project_id", help="Project UUID to drive.")
    run_p.add_argument("--ticks", type=int, default=1000,
                       help="Max ticks per invocation (default 1000).")

    gate_p = sub.add_parser("gate", help="Human-gate operations (A2/A4).")
    gate_sub = gate_p.add_subparsers(dest="gate_command")
    gate_resolve = gate_sub.add_parser(
        "resolve", help="Resolve a parked HUMAN_GATE with a ratified verdict.")
    gate_resolve.add_argument("task_id")
    gate_resolve.add_argument("--verdict", required=True,
                              choices=["APPROVED", "REJECTED"])
    gate_resolve.add_argument("--project", dest="project_id", default=None,
                              help="Project UUID (resolved from the task when omitted).")
    gate_resolve.add_argument("--operator", required=True)
    gate_resolve.add_argument("--token", required=True)

    op_p = sub.add_parser("operator", help="Operator credentials (A4).")
    op_sub = op_p.add_subparsers(dest="operator_command")
    op_reg = op_sub.add_parser(
        "register", help="Register a ratified operator credential.")
    op_reg.add_argument("operator_id")
    op_reg.add_argument("--token", required=True)
    op_reg.add_argument("--name", default="")

    pause_p = sub.add_parser("pause", help="Pause the active project.")
    pause_p.add_argument("project_id", help="Project UUID.")

    resume_p = sub.add_parser("resume", help="Resume a paused project.")
    resume_p.add_argument("project_id", help="Project UUID to resume.")

    vault_p = sub.add_parser(
        "vault", help="Vault projection (derived views; P-AUTO-5).")
    vault_sub = vault_p.add_subparsers(dest="vault_command")
    vault_proj = vault_sub.add_parser(
        "project", help="Project journal rows into vault notes + manifest.")
    vault_proj.add_argument("project_id", help="Project UUID to project.")
    vault_proj.add_argument("--vault-root", dest="vault_root", required=True,
                            help="Absolute vault root (human-owned areas "
                                 "are refused).")
    vault_verify = vault_sub.add_parser(
        "verify", help="Recompute the manifest from the journal and diff.")
    vault_verify.add_argument("project_id", help="Project UUID to verify.")
    vault_verify.add_argument("--vault-root", dest="vault_root",
                              required=True,
                              help="Absolute vault root to verify.")
    vault_verify.add_argument("--json", dest="as_json", action="store_true",
                              help="Emit the verification report as one JSON "
                                   "document (stable schema: {\"verify\", "
                                   "\"ok\", \"findings\": [...]}); exit is "
                                   "1 when refused.")

    return p


def _load_config_or_default(config_arg: Path | None) -> HermesConfig:
    if config_arg:
        return load_config(config_arg)
    candidates = [Path("config") / "hermes.toml", Path("hermes.toml")]
    for c in candidates:
        if c.exists():
            try:
                return load_config(c)
            except ConfigError as exc:
                # B4 — never SILENTLY disable operator settings on a typo'd
                # config: the fallback is loud (stderr) and the operator can
                # see exactly what was rejected and what is running instead.
                emit(f"warning: ignoring invalid config {c}: {exc}",
                      file=sys.stderr)
                emit("  running on built-in defaults", file=sys.stderr)
                return default_config()
    return default_config()


def _dispatch(args: argparse.Namespace, cfg: HermesConfig,
              parser: argparse.ArgumentParser) -> int:
    """Route one parsed command to its handler (the CLI's emit boundary)."""
    cmd = args.command
    if cmd is None:
        parser.print_help()
        return 0
    if cmd == "doctor":
        return _doctor(args, cfg)
    if cmd == "backup":
        return _backup(args, cfg)
    if cmd == "restore":
        return _restore(args, cfg)
    if cmd == "init":
        return _init(args, cfg)
    if cmd == "status":
        return _status(args, cfg)
    if cmd == "audit":
        return _audit(args, cfg)
    if cmd == "project":
        pc = getattr(args, "project_command", None)
        if pc == "create":
            return _project_create(args, cfg)
        if pc == "show":
            return _project_show(args, cfg)
        emit("Usage: hermes project {create|show} ...")
        return 0
    if cmd == "task":
        tc = getattr(args, "task_command", None)
        if tc == "show":
            return _task_show(args, cfg)
        emit("Usage: hermes task show <task_id>")
        return 0
    if cmd == "events":
        return _events(args, cfg)
    if cmd == "pause":
        return _pause(args, cfg)
    if cmd == "resume":
        return _resume(args, cfg)
    if cmd == "vault":
        vc = getattr(args, "vault_command", None)
        if vc == "project":
            return _vault_project(args, cfg)
        if vc == "verify":
            return _vault_verify(args, cfg)
        emit("Usage: hermes vault {project|verify} <project_id> "
              "--vault-root <path>")
        return 0
    if cmd == "run":
        return _run(args, cfg)
    if cmd == "gate":
        gc = getattr(args, "gate_command", None)
        if gc == "resolve":
            return _gate_resolve(args, cfg)
        emit("Usage: hermes gate resolve <task_id> "
              "--verdict APPROVED|REJECTED --operator <id> --token <token>")
        return 0
    if cmd == "operator":
        oc = getattr(args, "operator_command", None)
        if oc == "register":
            return _operator_register(args, cfg)
        emit("Usage: hermes operator register <operator_id> "
              "--token <token> [--name <name>]")
        return 0
    parser.print_help()
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    cfg = _load_config_or_default(getattr(args, "config", None))
    # The emit boundary (EXT-5 / R3): a line the boundary cannot prove free
    # of terminal control sequences refuses loudly — fixed refusal line on
    # stderr (stdout stays parseable), nonzero exit — never raw bytes.
    return run_boundary(lambda: _dispatch(args, cfg, parser))


if __name__ == "__main__":
    raise SystemExit(main())
