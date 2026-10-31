# SPDX-License-Identifier: Apache-2.0
"""Seed one fresh methodology run through the spine's own write path.

Promoted from the run-38 probe. The script exists so a depth measurement can
start from a project that asserts nothing: it creates the project row through
``ProjectRepository`` (the same path the CLI uses) and admits the methodology
task with **one** ``INSERT_TASK`` intent through the gateway's single mutation
path, ``apply_intent``. Nothing else is written; no substrate node, no artifact
and no prior-art registration is fabricated here.

Dry-run by default
------------------
Without ``--apply`` the script:
- refuses a missing journal (it will not create one to inspect it),
- parses the methodology and prints its stages,
- checks that the project and task ids are free,
- prints the exact intent it would admit (kind, project, task, question, refs),
- writes nothing.

``--apply`` creates the project when absent and admits the task. The project
row is the one durable effect that does not route through ``apply_intent`` —
there is no project-creation intent in this build, and the CLI creates projects
through the same repository. If admission is refused afterwards, the empty
project row remains and the operator can reuse it.

Prior art
---------
``--admission-ref REF`` names a ref the run may treat as prior art. Since
OPS-5Y a ref is backed only by a project row (an ``evidence:`` artifact, a
``claim:`` row, or a hypothesis/prediction embedded in a ``research_programs``
row); the run refuses an unbacked entry at intake. This script checks each ref
through the same read-only port the run uses and refuses before seeding when a
row does not carry it. A **fresh** project has no rows, so a backed ref can
only be seeded into an existing project (``--allow-existing-project``); without
that flag a non-empty ref list is refused with that explanation.

``--cite KIND=REF`` names a prior-art ref a minted stage cites. The same ref is
added to ``admission_refs`` because a citation must resolve in the project; a
cited ref that no row carries makes the run refuse.

The provider is **not** selected here: the run's model comes from the composed
tier configuration. ``--provider`` is recorded in the intent's justification so
the operator's intended target is visible in the journal; it changes no
behaviour.

Usage (from the repo root)::

    python scripts/seed_methodology_run.py --db D:/New folder/hermes-live.db \\
        --project sars-covid-39 --question "why was SARS contained?" --provider \
        deepseek-v4.1-flash

    python scripts/seed_methodology_run.py ... --apply

Exit status: 0 when the plan is printed (dry-run) or the seed is admitted;
1 when a precondition or the gateway refuses; 2 on a malformed argument.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence

REPO_ROOT = Path(__file__).resolve().parents[1]
_SRC = REPO_ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from hermes.core.intents import Intent, IntentKind  # noqa: E402
from hermes.methodology.workflows import (  # noqa: E402
    LITERATURE_REVIEW_DOCUMENT,
    MethodologyConfigError,
    parse_methodology,
)
from hermes.persistence.database import connect  # noqa: E402
from hermes.persistence.migrations import migrate_to_latest  # noqa: E402
from hermes.persistence.repositories import ProjectRepository  # noqa: E402
from hermes.research.chain_refs import RefProvenanceReader  # noqa: E402
from hermes.research.gateway import GatewayRejection, apply_intent  # noqa: E402

TEMPLATE = "methodology_run"
DEFAULT_PROFILE = "RESEARCHER"
DEFAULT_MAX_RETRIES = 3
#: The stages that may carry a prior-art citation (minted kinds, OPS-5Y). The
#: evidence position is deliberately absent: it is agent-derived (OPS-5D).
CITE_KINDS: tuple[str, ...] = ("HYPOTHESIS", "PREDICTION", "CLAIM")


class SeedError(ValueError):
    """A precondition this script refuses to seed through."""


def _read_conn(path: Path) -> sqlite3.Connection:
    """Open an existing journal read-only — a dry run never creates one."""
    uri = "file:" + path.resolve().as_posix() + "?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def _write_conn(path: Path) -> sqlite3.Connection:
    conn = connect(path)
    migrate_to_latest(conn)
    return conn


def _project_exists(conn: sqlite3.Connection, project_id: str) -> bool:
    return conn.execute("SELECT 1 FROM projects WHERE project_id = ?",
                        (project_id,)).fetchone() is not None


def _task_exists(conn: sqlite3.Connection, task_id: str) -> bool:
    return conn.execute("SELECT 1 FROM tasks WHERE task_id = ?",
                        (task_id,)).fetchone() is not None


def _parse_cite(value: str) -> tuple[str, str]:
    kind, separator, ref = value.partition("=")
    kind = kind.strip().upper()
    ref = ref.strip()
    if not separator or kind not in CITE_KINDS or not ref:
        raise argparse.ArgumentTypeError(
            f"--cite expects KIND=REF with KIND in {list(CITE_KINDS)}; "
            f"got {value!r}")
    return kind, ref


def load_methodology(conn: sqlite3.Connection,
                     source_task: str) -> Mapping[str, Any]:
    """The methodology document: copied from a task, or the shipped one.

    Copying is for *replicating* a historical run's document; a fresh
    measurement should use the shipped document, which is the only one this
    tree corrects (OPS-5Y changed three stage objectives).
    """
    if not source_task:
        return dict(LITERATURE_REVIEW_DOCUMENT)
    row = conn.execute(
        "SELECT spec_json FROM tasks WHERE task_id = ?",
        (source_task,)).fetchone()
    if row is None:
        raise SeedError(
            f"methodology source task {source_task!r} does not exist")
    try:
        spec = json.loads(row["spec_json"] or "{}")
    except ValueError as error:
        raise SeedError(
            f"methodology source task {source_task!r} has unreadable spec "
            f"JSON: {error}") from error
    document = spec.get("methodology") if isinstance(spec, dict) else None
    if not isinstance(document, dict):
        raise SeedError(
            f"methodology source task {source_task!r} carries no "
            f"spec.methodology mapping")
    return document


def build_intent(*, project_id: str, task_id: str, question: str,
                 methodology: Mapping[str, Any], admission_refs: Sequence[str],
                 external_refs: Mapping[str, str], provider: str,
                 profile: str, max_retries: int) -> Intent:
    """The one INSERT_TASK this script admits — fully determined, no clock."""
    justification = (
        "Seed one literature-review methodology run through apply_intent so a "
        "depth measurement starts from a project that asserts no prior art.")
    if provider:
        # A record of the operator's intended target, not a selection: the
        # run's model is chosen by the composed tier configuration.
        justification += f" Intended provider: {provider}."
    return Intent(
        kind=IntentKind.INSERT_TASK,
        proposed_by="DIRECTOR",
        project_id=project_id,
        payload={
            "task_id": task_id,
            "task_type": "AGENT_TASK",
            "profile": profile,
            "idempotency_key": f"k-{task_id}",
            "spec": {
                "template": TEMPLATE,
                "methodology": dict(methodology),
                "inputs": {
                    "question": question,
                    "admission_refs": list(admission_refs),
                    "external_refs": dict(external_refs),
                },
            },
            "inputs": [],
            "outputs": [],
            "dependencies": [],
            "provenance": [],
            "iteration": 1,
            "max_retries": max_retries,
            "cost_class": "LOW",
        },
        justification=justification,
    )


def _plan(intent: Intent, *, name: str, stages: Sequence[str],
          provider: str) -> dict[str, Any]:
    spec = dict(intent.payload.get("spec") or {})
    inputs = dict(spec.get("inputs") or {})
    return {
        "dry_run": True,
        "project": intent.project_id,
        "name": name,
        "task_id": intent.payload.get("task_id"),
        "intent_kind": intent.kind.value,
        "profile": intent.payload.get("profile"),
        "question": inputs.get("question"),
        "admission_refs": inputs.get("admission_refs"),
        "external_refs": inputs.get("external_refs"),
        "provider_note": provider or "(not named)",
        "stages": list(stages),
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=("Seed one fresh methodology task through apply_intent; "
                     "dry-run unless --apply is given."))
    parser.add_argument("--db", required=True, type=Path,
                        help="Path to the SQLite journal.")
    parser.add_argument("--project", required=True,
                        help="The new project id (must not exist).")
    parser.add_argument("--name", default="",
                        help="The project name (default: the project id).")
    parser.add_argument("--question", required=True,
                        help="The run's question.")
    parser.add_argument("--task-id", default="",
                        help="The methodology task id (default: meth-<project>).")
    parser.add_argument("--admission-ref", action="append", default=[],
                        metavar="REF",
                        help="A prior-art ref the run may treat as backed; "
                             "repeatable.")
    parser.add_argument("--cite", action="append", default=[],
                        type=_parse_cite, metavar="KIND=REF",
                        help=(f"A prior-art citation on a minted stage "
                              f"({', '.join(CITE_KINDS)}); repeatable. The "
                              f"ref is also added to admission_refs."))
    parser.add_argument("--methodology-from-task", default="",
                        metavar="TASK_ID",
                        help=("Copy the methodology document from an existing "
                              "task (historical replication); default: the "
                              "shipped literature-review document."))
    parser.add_argument("--provider", default="",
                        help=("Record the intended model provider in the "
                              "intent's justification; it does not select the "
                              "run's model."))
    parser.add_argument("--allow-existing-project", action="store_true",
                        help=("Seed into an existing project instead of "
                              "creating one. Required for a backed "
                              "--admission-ref/--cite: a fresh project has no "
                              "row that could carry one."))
    parser.add_argument("--profile", default=DEFAULT_PROFILE,
                        help=f"The task profile (default: {DEFAULT_PROFILE}).")
    parser.add_argument("--max-retries", type=int,
                        default=DEFAULT_MAX_RETRIES,
                        help=f"Task retry budget (default: "
                             f"{DEFAULT_MAX_RETRIES}).")
    parser.add_argument("--apply", action="store_true",
                        help="Write the project and the task; without it the "
                             "script only prints the plan.")
    args = parser.parse_args(argv)

    name = args.name or args.project
    task_id = args.task_id or f"meth-{args.project}"
    if not args.db.exists():
        print(f"REFUSE: journal {args.db} does not exist", file=sys.stderr)
        return 1
    if args.max_retries < 0:
        print("REFUSE: --max-retries must be >= 0", file=sys.stderr)
        return 2

    external_refs: dict[str, str] = {}
    admission_refs = list(args.admission_ref)
    for kind, ref in args.cite:
        if kind in external_refs and external_refs[kind] != ref:
            print(f"REFUSE: --cite names two refs for {kind}", file=sys.stderr)
            return 2
        external_refs[kind] = ref
        admission_refs.append(ref)
    admission_refs = sorted(set(admission_refs))

    conn = _read_conn(args.db) if not args.apply else _write_conn(args.db)
    try:
        exists = _project_exists(conn, args.project)
        if exists and not args.allow_existing_project:
            print(f"REFUSE: project {args.project!r} already exists — this "
                  f"script never reuses a project without "
                  f"--allow-existing-project", file=sys.stderr)
            return 1
        if not exists and args.allow_existing_project:
            print(f"REFUSE: project {args.project!r} does not exist — "
                  f"--allow-existing-project seeds into an existing one",
                  file=sys.stderr)
            return 1
        if _task_exists(conn, task_id):
            print(f"REFUSE: task {task_id!r} already exists", file=sys.stderr)
            return 1
        if admission_refs and not exists:
            print(f"REFUSE: {len(admission_refs)} ref(s) were named but "
                  f"project {args.project!r} does not exist yet — a fresh "
                  f"project has no row to back them; create the project and "
                  f"its rows first, then seed with --allow-existing-project",
                  file=sys.stderr)
            return 1
        provenance_of = RefProvenanceReader(conn)
        for ref in admission_refs:
            origin = provenance_of(args.project, ref)
            if origin is None:
                print(f"REFUSE: ref {ref!r} does not resolve to a row in "
                      f"project {args.project!r} — an assertion is not an "
                      f"artifact", file=sys.stderr)
                return 1
        try:
            methodology = load_methodology(conn, args.methodology_from_task)
            config = parse_methodology(dict(methodology))
        except (SeedError, MethodologyConfigError) as error:
            print(f"REFUSE: {error}", file=sys.stderr)
            return 1

        intent = build_intent(
            project_id=args.project, task_id=task_id, question=args.question,
            methodology=methodology, admission_refs=admission_refs,
            external_refs=external_refs, provider=args.provider,
            profile=args.profile, max_retries=args.max_retries)

        if not args.apply:
            print(json.dumps(
                _plan(intent, name=name, stages=config.stage_kinds(),
                      provider=args.provider),
                indent=2, sort_keys=True))
            return 0

        if not exists:
            ProjectRepository(conn).create(args.project, name)
            print(f"project created: {args.project}")
        else:
            print(f"project reused: {args.project}")
        try:
            result = apply_intent(conn, intent)
        except GatewayRejection as rejection:
            print(f"REFUSED {rejection.code}: {rejection.reason}",
                  file=sys.stderr)
            if not exists:
                print(f"note: project {args.project!r} was created and remains "
                      f"empty", file=sys.stderr)
            return 1
        print(f"task admitted: {result.entity_id}")
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
