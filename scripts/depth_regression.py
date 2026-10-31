"""Depth ratchet — the pipeline may not reach less far than it did.

`depth_report.py` measures how deep a run got. This pins it. The pipeline's
reach is the one *system-level* property the per-slice falsifiers cannot see:
a slice can pass every test it writes and still leave the chain stopping one
stage earlier, because no test was asking about reach.

Run 38 reached PREDICTION (2 of 9) with prior art that did not exist; run 39
reached QUESTION (1 of 9) with none. The second is the honest number, and it is
*lower* — which is exactly why the ratchet needs an audited allowance rather
than a bare threshold. A decrease is not automatically a regression, but it may
never be silent.

    python scripts/depth_regression.py --db ... --baseline docs/DEPTH-RATCHET.json
    python scripts/depth_regression.py ... --update --note "5Y landed; v3 doc"
    python scripts/depth_regression.py ... --allow-decrease "why it fell"

Exit 0 when the current depth meets or exceeds the ratchet, 1 when it is lower
and no allowance was given, 2 on an unusable baseline.
"""
from __future__ import annotations

import argparse
import contextlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parent))

import depth_report


def read_baseline(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"ratchet": None, "history": []}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        print(f"{path} is not valid JSON: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc
    if not isinstance(data, dict) or "ratchet" not in data:
        print(f"{path} has no 'ratchet' object", file=sys.stderr)
        raise SystemExit(2)
    return data


def current_depth(db: Path) -> dict[str, Any]:
    """The deepest stage a run reaches *now*, from each project's latest field.

    Not the historical maximum. `depth_report` keeps a project's deepest row
    ever seen (`recorded >= previous`), which is right for "how far has this
    project ever got" and wrong for a ratchet: an append-only journal keeps the
    old deep row forever, so a later, shallower run could never lower the
    number. The gate would then pass the exact regression it exists to catch.

    So this reads the **last** field-bearing event per project and takes the
    maximum across those. A project that ran deep yesterday and shallow today
    contributes today's number.
    """
    conn = depth_report.connect_readonly(db)
    try:
        rows = conn.execute(
            "select project_id, payload_json from events "
            "where event_type='TaskStatusChanged' and project_id is not null "
            "order by event_id").fetchall()
    finally:
        conn.close()

    latest: dict[str, dict[str, Any]] = {}
    for row in rows:
        payload = depth_report._payload(row["payload_json"])
        if ("stages_recorded" not in payload
                and "stage_reached" not in payload):
            continue
        latest[row["project_id"]] = {
            "depth": int(payload.get("stages_recorded") or 0),
            "stage_reached": str(payload.get("stage_reached") or ""),
            "refusal_code": str(payload.get("refusal_code") or ""),
        }
    if not latest:
        return {"depth": 0, "stage": None, "project": None,
                "projects_measured": 0, "measurable": False}

    project, best = max(latest.items(), key=lambda kv: kv[1]["depth"])
    return {
        "projects": {name: row["depth"] for name, row in latest.items()},
        "depth": best["depth"],
        # The stage the run *attempted*, which the payload records separately
        # from the count of stages it managed to record.
        "stage": best["stage_reached"] or None,
        "project": project,
        "projects_measured": len(latest),
        "measurable": True,
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--db", required=True, type=Path)
    parser.add_argument("--baseline", required=True, type=Path)
    parser.add_argument("--update", action="store_true",
                        help="Record the current depth as the new ratchet.")
    parser.add_argument("--allow-decrease", default="",
                        help="Permit a decrease, and record why.")
    parser.add_argument("--note", default="", help="Context stored with --update.")
    args = parser.parse_args(argv)

    with contextlib.suppress(AttributeError, OSError):
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")

    if not args.db.exists():
        print(f"no such journal: {args.db}", file=sys.stderr)
        return 2

    # A missing baseline is a misconfiguration, not "nothing to check yet". The
    # first draft passed here, so a typo in the path silently disabled the gate.
    if not args.baseline.exists() and not args.update:
        print(f"no baseline at {args.baseline} — a missing ratchet is not a "
              f"pass. Run with --update to record one.", file=sys.stderr)
        return 2

    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    baseline = read_baseline(args.baseline)
    ratchet = baseline.get("ratchet")
    current = current_depth(args.db)

    print(f"ratchet : {ratchet['depth'] if ratchet else 'none'} "
          f"({ratchet['stage'] if ratchet else '-'})"
          f"{' in ' + str(ratchet['project']) if ratchet and ratchet.get('project') else ''}")
    print(f"current : {current['depth']} ({current['stage'] or '-'})"
          f"{' in ' + str(current['project']) if current.get('project') else ''}"
          f"  [{current['projects_measured']} project(s) measured]")

    # No field-bearing event anywhere means the question cannot be answered.
    # Reporting 0 would claim a depth nobody measured, and would let a
    # field-less journal pass against a ratchet of 0.
    if not current["measurable"]:
        print("UNMEASURABLE — this journal carries no field-derived depth, so "
              "reach cannot be compared. Not a pass.")
        return 1

    # Computed before the update branch: --update must demand a reason for a
    # regression exactly where the compare path does. The first version only
    # demanded one when the *global* depth fell, so a bare --update laundered a
    # project that had gone backwards.
    known_projects = dict(baseline.get("projects") or {})
    regressed = {name: (recorded, current["projects"][name])
                 for name, recorded in known_projects.items()
                 if name in current["projects"]
                 and current["projects"][name] < recorded}
    # A project the baseline tracks but this journal no longer measures is
    # unmeasurable, not "held".
    missing_projects = sorted(set(known_projects) - set(current["projects"]))
    uninitialised = ratchet is not None and "projects" not in baseline

    if args.update:
        if ((ratchet is not None and current["depth"] < ratchet["depth"])
                or regressed) and not (args.note or args.allow_decrease):
            if ratchet is not None and current["depth"] < ratchet["depth"]:
                why = (f"lower the ratchet from {ratchet['depth']} to "
                       f"{current['depth']}")
            else:
                names = ", ".join(f"{n} {was}->{now}"
                                  for n, (was, now) in sorted(regressed.items()))
                why = f"record a project regression ({names})"
            print(f"refusing to {why} without a stated reason — pass --note "
                  f"\"<why>\" or --allow-decrease \"<why>\".")
            return 1
        baseline["projects"] = dict(current.get("projects") or {})
        entry = {**current, "recorded_at": now, "note": args.note}
        baseline.setdefault("history", []).append(
            {"from": ratchet, "to": entry, "reason": args.note or "update"})
        baseline["ratchet"] = entry
        args.baseline.parent.mkdir(parents=True, exist_ok=True)
        args.baseline.write_text(
            json.dumps(baseline, indent=2, sort_keys=True) + "\n",
            encoding="utf-8")
        print(f"ratchet updated -> {args.baseline}")
        return 0

    if ratchet is None:
        print("no ratchet recorded yet; run with --update to set one")
        return 0

    # Per-project: a project that went backwards is a regression even when a
    # deeper sibling keeps the global maximum up. The first repair compared the
    # global max only, so A regressing 3 -> 1 was masked by B sitting at 3.
    if (current["depth"] >= ratchet["depth"] and not regressed
            and not missing_projects and not uninitialised):
        if current["depth"] > ratchet["depth"]:
            print(f"REACH IMPROVED by {current['depth'] - ratchet['depth']} "
                  f"— record it with --update")
        else:
            print("reach held")
        return 0

    if regressed and current["depth"] >= ratchet["depth"]:
        for name, (was, now) in sorted(regressed.items()):
            print(f"PROJECT REGRESSED {name}: {was} -> {now}")
        print("  a deeper sibling does not excuse a project that reaches less")

    if args.allow_decrease:
        baseline.setdefault("history", []).append({
            "from": ratchet, "to": current, "reason": args.allow_decrease,
            "allowed_at": now})
        args.baseline.write_text(
            json.dumps(baseline, indent=2, sort_keys=True) + "\n",
            encoding="utf-8")
        print(f"REACH FELL by {ratchet['depth'] - current['depth']} — allowed: "
              f"{args.allow_decrease}")
        return 0

    if uninitialised:
        print("BASELINE HAS NO 'projects' KEY — per-project tracking is not "
              "initialised, so a regression cannot be detected. Re-record with "
              "--update.")
    for name in missing_projects:
        print(f"PROJECT NOT MEASURED {name}: the baseline tracks it, this "
              f"journal has no field event for it — unmeasurable, not held")
    if current["depth"] < ratchet["depth"]:
        print(f"REACH FELL by {ratchet['depth'] - current['depth']} and no "
              f"allowance was given.")
    if regressed:
        print(f"{len(regressed)} project(s) regressed and no allowance was "
              f"given.")
    print("  A decrease may be correct (an honest floor can be lower than a "
          "seeded one), but it may not be silent.\n"
          "  Re-run with --allow-decrease \"<reason>\" or --update.")
    return 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except Exception:  # noqa: BLE001 - the exit status is the point
        import traceback
        traceback.print_exc()
        print("the gate itself failed — exit 2, not a finding", file=sys.stderr)
        raise SystemExit(2) from None
