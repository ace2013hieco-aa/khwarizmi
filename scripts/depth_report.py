"""Depth report — how far a Hermes run actually got, and where it stopped.

Read-only. Opens the journal with ``mode=ro`` and never writes, so it is safe
against a live database while a run is in flight.

The question this answers is not "did the run succeed" (that is the run
report's job) but "how deep did the chain get, and what stopped it". Three
kinds of evidence are used, in descending order of trust:

1. **Structured rows** — task states, applied-intent kinds, artifact types,
   claim/evidence/verdict counts. Facts.
2. **Typed reason prose** — the refusal text on ``TaskStatusChanged``. This is
   the *only* place a failure class is recorded, so it is parsed into classes
   and every class is labelled ``prose`` in the output. It is not data.
3. **Absence** — a table that is empty is reported as empty, never as zero
   "failures".

The report deliberately prints the gaps it cannot close. A run whose stage
progression was never recorded structurally cannot be measured by this tool,
and saying so is more useful than inferring a depth from a sentence.

Usage::

    python scripts/depth_report.py --db "D:/New folder/hermes-live.db"
    python scripts/depth_report.py --db ... --project sars-covid-22
    python scripts/depth_report.py --db ... --json > depth.json
"""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Sequence

#: The methodology's declared stage order, used only when a task's spec cannot
#: be read. A task that carries its own ``methodology.stages`` wins over this.
CANONICAL_STAGES: tuple[str, ...] = (
    "QUESTION", "HYPOTHESIS", "PREDICTION", "EXPERIMENT",
    "OBSERVATION", "EVIDENCE", "CLAIM", "CRITIQUE", "CONCLUSION",
)

#: ``... stopped early — termination 'MODEL_REFUSED' with 2 of 9 declared
#: stage(s) recorded`` — the only structured-ish statement of depth in the log.
STAGES_RECORDED = re.compile(
    r"with (\d+) of (\d+) declared stage\(s\) recorded")
TERMINATION = re.compile(r"termination '([A-Z_]+)'")
MALFORMED_NODE = re.compile(r"a ([A-Z_]+) node cites an existing artifact")
ADMISSIONS = re.compile(r"with (\d+) admissions")

#: Intent kinds that build the task graph rather than the research record. An
#: admitted one of these still counts toward `intents_applied`, which is what
#: the completion gate sums — so the split below is not cosmetic.
BOOKKEEPING_KINDS: frozenset[str] = frozenset({"INSERT_TASK", "ADMIT_TASK"})

#: Failure classes, most specific first. Each pattern is anchored on a phrase
#: the runtime actually emits, never on a guess.
FAILURE_CLASSES: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("MODEL_CHAIN_EXHAUSTED",
     re.compile(r"every candidate model in the fallback chain failed")),
    ("EFFECTLESS_RUN",
     re.compile(r"\d+ admissions via apply_intent")),
    ("MALFORMED_PAYLOAD", re.compile(r"\bMALFORMED_PAYLOAD\b")),
    ("TRUNCATED_CHAIN", re.compile(r"stopped early\b")),
    ("EVIDENCE_UNRESOLVED", re.compile(r"\bEVIDENCE_DOES_NOT_RESOLVE\b")),
    ("RETRY_EXHAUSTED", re.compile(r"attempts exhausted")),
)


def connect_readonly(path: Path) -> sqlite3.Connection:
    """Open the journal read-only. Never creates, never migrates."""
    uri = "file:" + path.as_posix() + "?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def has_table(conn: sqlite3.Connection, name: str) -> bool:
    row = conn.execute(
        "select 1 from sqlite_master where type='table' and name=?",
        (name,)).fetchone()
    return row is not None


def count(conn: sqlite3.Connection, sql: str, params: Sequence[Any] = ()) -> int:
    row = conn.execute(sql, params).fetchone()
    return int(row[0]) if row and row[0] is not None else 0


def scalar_map(conn: sqlite3.Connection, sql: str,
               params: Sequence[Any] = ()) -> dict[str, int]:
    """A ``{label: count}`` map, nulls and numbers coerced to a stable string."""
    out: dict[str, int] = {}
    for row in conn.execute(sql, params):
        label = row[0]
        out["<null>" if label is None else str(label)] = int(row[1])
    return dict(sorted(out.items()))


def classify(reason: str) -> tuple[str, str]:
    """``(class, detail)`` for one failure reason. ``detail`` narrows the class."""
    text = reason or ""
    for name, pattern in FAILURE_CLASSES:
        if pattern.search(text):
            if name == "TRUNCATED_CHAIN":
                termination = TERMINATION.search(text)
                return name, termination.group(1) if termination else "?"
            if name == "MALFORMED_PAYLOAD":
                node = MALFORMED_NODE.search(text)
                return name, (node.group(1) + " cites existing artifact"
                              if node else "other")
            if name == "EFFECTLESS_RUN":
                admissions = ADMISSIONS.search(text)
                return name, (f"admissions={admissions.group(1)}"
                              if admissions else "admissions=0")
            return name, ""
    if not text.strip():
        return "UNREASONED", "empty reason"
    return "OTHER", text.strip()[:80]


def declared_stages(conn: sqlite3.Connection) -> tuple[str, ...]:
    """Stage order from a task's own methodology spec, else the canonical order."""
    if not has_table(conn, "tasks"):
        return CANONICAL_STAGES
    for (spec,) in conn.execute(
            "select spec_json from tasks where spec_json like '%\"stages\"%' "
            "and spec_json is not null limit 1"):
        try:
            stages = json.loads(spec)["methodology"]["stages"]
        except (KeyError, TypeError, ValueError):
            continue
        names = tuple(str(s.get("stage")) for s in stages if s.get("stage"))
        if names:
            return names
    return CANONICAL_STAGES


def _payload(raw: Any) -> dict[str, Any]:
    """An event payload, or ``{}`` when absent/unreadable (fail closed)."""
    try:
        value = json.loads(raw or "{}")
    except (TypeError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def depth_rows(conn: sqlite3.Connection, stages: Sequence[str],
               project: str | None = None) -> list[dict[str, Any]]:
    """Per project: the deepest recorded stage, and what the record says stopped it.

    OPS-5Y: the **field** wins. A ``TaskStatusChanged`` payload carrying
    ``stages_recorded`` / ``stage_reached`` / ``refusal_code`` /
    ``backing_class`` is a typed record (``depth_source: "field"``); the
    historical prose regex is the fallback (``"prose"``); neither is
    ``"unrecorded"``. A field row is preferred when its ``stages_recorded`` is
    at least as deep as the current one, so a later dispatch supersedes an
    earlier one.
    """
    scope = " and project_id = ?" if project else ""
    params: tuple[Any, ...] = (project,) if project else ()
    reasons: dict[str, list[str]] = defaultdict(list)
    field: dict[str, dict[str, Any]] = {}
    for row in conn.execute(
            "select project_id, to_state, reason, payload_json from events "
            "where event_type='TaskStatusChanged' and project_id is not null"
            + scope + " order by event_id", params):
        if row["to_state"] in ("FAILED", "CANCELLED") and row["reason"]:
            reasons[row["project_id"]].append(str(row["reason"]))
        payload = _payload(row["payload_json"])
        if ("stages_recorded" not in payload
                and "stage_reached" not in payload):
            continue
        recorded = int(payload.get("stages_recorded") or 0)
        previous = field.get(row["project_id"])
        if previous is None or recorded >= int(
                previous.get("stages_recorded") or 0):
            field[row["project_id"]] = {
                "stages_recorded": recorded,
                "stages_declared": payload.get("stages_declared"),
                "stage_reached": str(payload.get("stage_reached") or ""),
                "refusal_code": str(payload.get("refusal_code") or ""),
                "backing_class": str(payload.get("backing_class") or ""),
            }

    claims = {r[0] for r in conn.execute(
        "select distinct project_id from research_claims where 1=1" + scope,
        params)} \
        if has_table(conn, "research_claims") else set()
    artifacts: dict[str, Counter[str]] = defaultdict(Counter)
    if has_table(conn, "artifacts"):
        for row in conn.execute(
                "select project_id, artifact_type from artifacts where 1=1"
                + scope, params):
            artifacts[row[0]][str(row[1])] += 1

    task_states: dict[str, Counter[str]] = defaultdict(Counter)
    for row in conn.execute(
            "select project_id, status, count(*) from tasks where 1=1"
            + scope + " group by 1,2", params):
        task_states[row[0]][str(row[1])] = int(row[2])

    out: list[dict[str, Any]] = []
    for project in sorted(reasons | task_states):
        field_row = field.get(project)
        recorded = 0
        if field_row is not None:
            recorded = int(field_row.get("stages_recorded") or 0)
            source = "field"
        else:
            for reason in reasons[project]:
                m = STAGES_RECORDED.search(reason)
                if m:
                    recorded = max(recorded, int(m.group(1)))
            source = "prose" if recorded else "unrecorded"
        deepest = (stages[recorded - 1]
                   if 0 < recorded <= len(stages) else None)
        stage_reached = (
            str(field_row.get("stage_reached") or "") if field_row is not None
            else (deepest or ""))
        classes = Counter()
        for reason in reasons[project]:
            name, detail = classify(reason)
            classes[f"{name}:{detail}" if detail else name] += 1
        out.append({
            "project_id": project,
            "stages_recorded": recorded or None,
            "stages_declared": (field_row.get("stages_declared")
                                if field_row is not None else None),
            "deepest_stage": deepest,
            "stage_reached": stage_reached or None,
            "refusal_code": (field_row.get("refusal_code") or None
                             if field_row is not None else None),
            "backing_class": (field_row.get("backing_class") or None
                              if field_row is not None else None),
            "depth_source": source,
            "depth_known": deepest is not None or bool(stage_reached),
            "tasks": dict(sorted(task_states[project].items())),
            "claims": project in claims,
            "artifacts": dict(sorted(artifacts[project].items())),
            "terminal_classes": dict(sorted(classes.items())),
        })
    return out


def build(conn: sqlite3.Connection, project: str | None = None) -> dict[str, Any]:
    # Two forms, because half the queries below already carry a WHERE: `where`
    # opens one, `and_` extends one. Using the wrong one is a syntax error, so
    # they are named for what they do rather than for where they go.
    where = " where project_id = ?" if project else ""
    and_ = " and project_id = ?" if project else ""
    params: tuple[Any, ...] = (project,) if project else ()
    stages = declared_stages(conn)
    report: dict[str, Any] = {
        "scope": {"project": project, "stage_order": list(stages)},
        "census": {
            "projects": count(conn, "select count(*) from projects" + where, params),
            "lifecycle": scalar_map(
                conn, "select lifecycle_state, count(*) from projects" + where
                + " group by 1", params),
            "events": count(conn, "select count(*) from events" + where, params),
            "event_types": scalar_map(
                conn, "select event_type, count(*) from events" + where
                + " group by 1", params),
            "tasks": scalar_map(
                conn, "select status, count(*) from tasks" + where
                + " group by 1", params),
            "task_profiles": scalar_map(
                conn, "select profile, count(*) from tasks" + where
                + " group by 1", params),
            "applied_intents": scalar_map(
                conn, "select json_extract(payload_json,'$.intent_kind'), count(*) "
                      "from events where event_type='IntentApplied'" + and_
                + " group by 1", params),
            "rejected_intents": scalar_map(
                conn, "select json_extract(payload_json,'$.intent_kind'), count(*) "
                      "from events where event_type='IntentRejected'" + and_
                + " group by 1", params),
            "rejected_by": scalar_map(
                conn, "select json_extract(payload_json,'$.proposed_by'), count(*) "
                      "from events where event_type='IntentRejected'" + and_
                + " group by 1", params),
            "artifacts": scalar_map(
                conn, "select artifact_type, count(*) from artifacts" + where
                + " group by 1", params),
        },
        "substance": {},
        "depth": depth_rows(conn, stages, project),
        "failures": {},
        "frontier": {},
        "gaps": {},
    }

    for table in ("research_claims", "evidence_ladder_state",
                  "validation_verdicts", "research_programs"):
        if has_table(conn, table):
            report["substance"][table] = count(
                conn, f"select count(*) from {table}" + where, params)
        else:
            report["substance"][table] = None

    # ── the split that decides whether "completed" means anything ──
    # The completion gate sums `intents_applied`, which counts every ADMITTED
    # proposal regardless of kind. A task insertion is therefore a research
    # admission as far as S6-B2 is concerned. Separating the two here is the
    # whole point of the report: it is the difference between the loop doing
    # work and the loop scheduling work.
    applied = report["census"]["applied_intents"]
    bookkeeping = sum(v for k, v in applied.items() if k in BOOKKEEPING_KINDS)
    substantive = sum(v for k, v in applied.items() if k not in BOOKKEEPING_KINDS)
    report["census"]["applied_split"] = {
        "bookkeeping": bookkeeping,
        "substantive": substantive,
    }

    # ── verdict: the one line a milestone question should be answered with ──
    rows = report["depth"]
    known = [r for r in rows if r["depth_known"]]
    deepest = (max(known, key=lambda r: r["stages_recorded"] or 0)
               if known else None)
    completed = count(
        conn,
        "select count(*) from events where event_type='TaskStatusChanged' "
        "and to_state='SUCCEEDED' and reason like '%methodology_run%completed%'"
        + and_, params)
    report["verdict"] = {
        "deepest_stage": deepest["deepest_stage"] if deepest else None,
        "deepest_stage_index": deepest["stages_recorded"] if deepest else None,
        "deepest_project": deepest["project_id"] if deepest else None,
        "stage_count": len(stages),
        "projects_with_known_depth": len(known),
        "projects_total": len(rows),
        "claims": report["substance"].get("research_claims"),
        "substantive_admissions": substantive,
        "bookkeeping_admissions": bookkeeping,
        "runs_reporting_completed": completed,
        "depth_sources": dict(Counter(row["depth_source"] for row in rows)),
    }

    # ── failures: prose, and labelled as such ──
    classes: Counter[str] = Counter()
    examples: dict[str, str] = {}
    first_last: dict[str, list[str]] = {}
    for row in conn.execute(
            "select reason, created_at from events where event_type="
            "'TaskStatusChanged' and reason is not null and reason != ''"
            + (" and project_id = ?" if project else "") + " order by created_at",
            params):
        name, detail = classify(str(row["reason"]))
        key = f"{name}:{detail}" if detail else name
        classes[key] += 1
        examples.setdefault(key, str(row["reason"])[:160])
        span = first_last.setdefault(key, [str(row["created_at"])] * 2)
        span[1] = str(row["created_at"])
    report["failures"] = {
        "source": "prose — parsed from TaskStatusChanged.reason, not a typed field",
        "classes": dict(classes.most_common()),
        "examples": dict(sorted(examples.items())),
        "first_last": dict(sorted(first_last.items())),
    }

    # ── frontier: what is left undone, and whether anything blocks it ──
    pending = scalar_map(
        conn, "select profile || ' / ' || task_type, count(*) from tasks "
              "where status='PENDING'" + (" and project_id = ?" if project else "")
        + " group by 1", params)
    blocked = 0
    if has_table(conn, "task_dependencies"):
        blocked = count(
            conn,
            "select count(*) from task_dependencies d join tasks t "
            "on t.task_id = d.task_id where t.status='PENDING'"
            + (" and t.project_id = ?" if project else ""), params)
    report["frontier"] = {
        "pending_by_profile": pending,
        "pending_total": sum(pending.values()),
        "pending_with_dependencies": blocked,
        "cancelled_reasons": scalar_map(
            conn, "select reason, count(*) from events where "
                  "event_type='TaskStatusChanged' and to_state='CANCELLED'"
            + (" and project_id = ?" if project else "") + " group by 1", params),
    }

    # ── gaps: what the record cannot tell us ──
    rejections = count(conn, "select count(*) from events where "
                             "event_type='IntentRejected'" + and_, params)
    bare = count(conn, "select count(*) from events where "
                       "event_type='IntentRejected' and (reason is null or "
                       "reason='intent rejected')" + and_, params)
    field_rows = sum(1 for row in report["depth"]
                     if row["depth_source"] == "field")
    report["gaps"] = {
        "rejections_without_diagnostic_reason": bare,
        "rejections_total": rejections,
        "stage_progression_is_structured": field_rows > 0,
        "projects_with_field_depth": field_rows,
        "note": ("A rejection records that an intent was refused, not why: no "
                 "refusal code and no validator message reach the journal. "
                 "Stage progression is a typed field on TaskStatusChanged when "
                 "the handler reports it (OPS-5Y); a row without one falls back "
                 "to prose inside a failure reason, and every row names its "
                 "source."),
    }
    return report


def _bar(value: int, total: int, width: int = 24) -> str:
    if total <= 0:
        return ""
    filled = round(width * value / total)
    return "#" * filled + "." * (width - filled)


def render(report: dict[str, Any]) -> str:
    lines: list[str] = []
    add = lines.append
    scope = report["scope"]
    add("DEPTH REPORT" + (f" — project {scope['project']}" if scope["project"]
                          else " — all projects"))
    add("=" * 78)

    v = report["verdict"]
    add("")
    add("VERDICT")
    add(f"  deepest stage ever recorded   {v['deepest_stage'] or 'none recorded'}"
        f" ({v['deepest_stage_index'] or 0} of {v['stage_count']})"
        f"{' in ' + v['deepest_project'] if v['deepest_project'] else ''}")
    add(f"  depth known for               {v['projects_with_known_depth']}"
        f"/{v['projects_total']} projects")
    add(f"  runs reporting 'completed'    {v['runs_reporting_completed']}")
    add(f"  claims recorded               {v['claims']}")
    add(f"  admissions: substantive       {v['substantive_admissions']}"
        f"   bookkeeping {v['bookkeeping_admissions']}")

    c = report["census"]
    add("")
    add("CENSUS")
    add(f"  projects            {c['projects']}")
    add(f"  lifecycle           {c['lifecycle']}")
    add(f"  events              {c['events']}")
    add(f"  event types         {c['event_types']}")
    add(f"  tasks               {c['tasks']}")
    add(f"  task profiles       {c['task_profiles']}")
    add(f"  applied intents     {c['applied_intents']}")
    add(f"  rejected intents    {c['rejected_intents']}")
    add(f"  rejected by         {c['rejected_by']}")
    add(f"  artifacts           {c['artifacts']}")

    add("")
    add("SUBSTANCE — the tables a research result would land in")
    for table, value in report["substance"].items():
        add(f"  {table:<24} {'<absent>' if value is None else value}")

    add("")
    add("DEPTH — deepest recorded stage per project (field, else prose)")
    rows = report["depth"]
    known = [r for r in rows if r["depth_known"]]
    add(f"  {len(known)}/{len(rows)} projects carry a readable stage record")
    sources = Counter(row["depth_source"] for row in rows)
    add(f'  depth_source: "field" {sources.get("field", 0)}'
        f' | "prose" {sources.get("prose", 0)}'
        f' | "unrecorded" {sources.get("unrecorded", 0)}')
    add("")
    add(f"  {'project':<18} {'stage':<12} {'n':>2} {'src':<11} "
        f"{'reached':<12} {'refusal':<18} {'backing':<7} {'claims':<6} tasks")
    for row in rows:
        stage = row["deepest_stage"] or "unrecorded"
        add(f"  {row['project_id']:<18} {stage:<12} "
            f"{str(row['stages_recorded'] or '-'):>2} "
            f"{row['depth_source']:<11} "
            f"{str(row['stage_reached'] or '-'):<12} "
            f"{str(row['refusal_code'] or '-'):<18} "
            f"{str(row['backing_class'] or '-'):<7} "
            f"{'yes' if row['claims'] else 'no':<6} {row['tasks']}")
    if known:
        deepest = max(known, key=lambda r: r["stages_recorded"] or 0)
        add("")
        add(f"  deepest anywhere: {deepest['deepest_stage']} "
            f"({deepest['stages_recorded']} of "
            f"{len(scope['stage_order'])}) in {deepest['project_id']}")

    add("")
    add("FAILURES — " + report["failures"]["source"])
    total = sum(report["failures"]["classes"].values())
    for key, value in report["failures"]["classes"].items():
        span = report["failures"]["first_last"].get(key, ["", ""])
        add(f"  {value:>3} {_bar(value, total)} {key}")
        add(f"      first {span[0]}  last {span[1]}")
        example = report["failures"]["examples"].get(key, "")
        if example:
            add(f"      e.g. {example}")

    add("")
    add("FRONTIER — work declared and never done")
    f = report["frontier"]
    add(f"  pending             {f['pending_total']}")
    add(f"  blocked by deps     {f['pending_with_dependencies']}")
    for key, value in f["pending_by_profile"].items():
        add(f"      {value:>3} {key}")
    add(f"  cancelled reasons   {f['cancelled_reasons']}")

    add("")
    add("GAPS — what this record cannot answer")
    g = report["gaps"]
    add(f"  rejections with a diagnostic reason: "
        f"{g['rejections_total'] - g['rejections_without_diagnostic_reason']}"
        f"/{g['rejections_total']}")
    add(f"  stage progression recorded as data: "
        f"{'yes' if g['stage_progression_is_structured'] else 'NO'}"
        f" ({g['projects_with_field_depth']} project(s) with a field row)")
    add(f"  {g['note']}")
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Read-only depth report over a Hermes journal.")
    parser.add_argument("--db", required=True, type=Path,
                        help="Path to the SQLite journal (opened read-only).")
    parser.add_argument("--project", default=None,
                        help="Restrict to one project id.")
    parser.add_argument("--json", action="store_true",
                        help="Emit JSON instead of text.")
    args = parser.parse_args(argv)

    if not args.db.exists():
        print(f"no such journal: {args.db}", file=sys.stderr)
        return 2
    conn = connect_readonly(args.db)
    try:
        report = build(conn, args.project)
    finally:
        conn.close()
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(render(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
