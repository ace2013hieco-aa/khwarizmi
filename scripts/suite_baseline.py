"""Suite baseline — known failures recorded, so a NEW one is loud.

The suite is not green on every machine. Five tests fail deterministically here
on SQLite threading and Windows symlink privileges, and they fail on the
untouched checkout too. A gate that says "all green" therefore cannot be met,
and a gate that is always red teaches everyone that red is normal — which is how
a gate dies.

So the gate is "no new failures". The known set is recorded, a new failure exits
1, and a known failure that stops failing is reported so the baseline shrinks
instead of going stale.

    python scripts/suite_baseline.py --baseline docs/SUITE-BASELINE.json
    python scripts/suite_baseline.py ... --update --note "why these are known"
    python scripts/suite_baseline.py ... --allow "reason this new one is known"
    python scripts/suite_baseline.py ... -- tests/test_x.py -k something

Failures are read from pytest's JUnit XML, never from console text. A run that
is killed before the report is written produces no report at all, and one killed
mid-write produces an unparseable file: both are exit 2, "not evidence". (The
first version of this docstring claimed a killed run "still yields a complete,
structured failure list" — it does not, and that claim was never tested.)

The dangerous case is narrower and was found by a redteam audit: a session that
aborts *after* junitxml has written, or raises in ``pytest_sessionfinish``,
exits 1 with a complete, failure-free report. Exit status and report disagree,
and the report is the one that looks clean. That is why a nonzero exit with zero
recorded failures is treated as a contradiction rather than a pass.

Exit codes: **0** no new failure, **1** a new failure, **2** the run could not be
used as evidence (no report, no baseline, contradictory exit status, no
testcases, internal error).
"""
from __future__ import annotations

import argparse
import contextlib
import json
import subprocess
import sys
import tempfile
import traceback
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

ROOT = Path(__file__).resolve().parent.parent
RUNNER = ROOT / "scripts" / "run_tests.py"


def _nodeid(case: ET.Element) -> str:
    """A stable ``file::Class::test`` key from one JUnit testcase.

    Built from ``classname`` always — never from ``file``. The first version
    preferred ``file`` when present and returned ``file::name``, which drops the
    class: the suite has six ``(file, leaf-name)`` pairs across classes, and
    under ``junit_family=xunit1`` (where ``file`` appears) swapping which class
    fails became invisible. ``classname`` is the dotted module path, optionally
    followed by the class, so the module is the longest prefix naming a real
    file — and the result uses forward slashes, which a ``file``-based key did
    not.
    """
    name = case.get("name") or ""
    parts = (case.get("classname") or "").split(".")
    module_len = 0
    for length in range(len(parts), 0, -1):
        candidate = ROOT.joinpath(*parts[:length]).with_suffix(".py")
        if candidate.exists():
            module_len = length
            break
    if not module_len:
        return f"{case.get('classname') or '?'}::{name}"
    rel = "/".join(parts[:module_len]) + ".py"
    classes = parts[module_len:]
    return f"{rel}::" + ("::".join(classes) + "::" if classes else "") + name


def run_suite(extra: Sequence[str]) -> tuple[int, list[str] | None, int, str]:
    """Run the suite through the canonical runner.

    Returns ``(returncode, failures, testcases, tail)``. ``failures`` is ``None``
    when there is no report at all; ``testcases`` is how many the report
    contains, which is the only way to tell a clean run from one that measured
    nothing.
    """
    with tempfile.TemporaryDirectory() as tmp:
        report = Path(tmp) / "junit.xml"
        cmd = [sys.executable, str(RUNNER), "-q", f"--junit-xml={report}",
               *extra]
        proc = subprocess.run(cmd, capture_output=True, text=True,
                              encoding="utf-8", timeout=7200)
        if not report.exists():
            # No structured report means the run is not evidence of anything.
            return proc.returncode, None, 0, (proc.stdout or "")[-1500:]
        tree = ET.parse(report)
    cases = list(tree.iter("testcase"))
    failures = sorted(
        _nodeid(case) for case in cases
        if any(child.tag in ("failure", "error") for child in case))
    return proc.returncode, failures, len(cases), ""


def compare(known: Sequence[str], flaky: Sequence[str],
            failures: Sequence[str]) -> dict[str, list[str]]:
    """What this run means against the baseline. Pure, so it can be tested.

    Three outcomes and no fourth: a failure the baseline does not know (``new``,
    the only one that gates), a failure the baseline knows is unreliable
    (``flaked``, reported and never gating), and a known failure that stopped
    failing (``fixed``, reported so the baseline can shrink).
    """
    known_set, flaky_set, failed = set(known), set(flaky), set(failures)
    return {
        "new": sorted(failed - known_set - flaky_set),
        "flaked": sorted(failed & flaky_set),
        "fixed": sorted(known_set - failed),
    }


def read_baseline(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        print(f"{path} is not valid JSON: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc
    if not isinstance(data, dict):
        print(f"{path} is not a baseline object", file=sys.stderr)
        raise SystemExit(2)
    return data


def write_baseline(path: Path, known: Sequence[str], note: str,
                   previous: dict[str, Any] | None,
                   flaky: Sequence[str] = ()) -> None:
    data = {
        "known_failures": sorted(known),
        "flaky": sorted(set(flaky) | set((previous or {}).get("flaky", []))),
        "recorded_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "note": note,
        "history": (previous or {}).get("history", []),
    }
    if previous is not None:
        data["history"].append({
            "known": len(previous.get("known_failures", [])),
            "reason": note or "update"})
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n",
                    encoding="utf-8")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--baseline", required=True, type=Path)
    parser.add_argument("--update", action="store_true",
                        help="Record the current failures as the known set.")
    parser.add_argument("--allow", default="",
                        help="Accept a NEW failure, and record why.")
    parser.add_argument("--note", default="", help="Context stored with --update.")
    parser.add_argument("--mark-flaky", action="append", default=[],
                        metavar="NODEID",
                        help="Record a failure as flaky: reported, never gating.")
    parser.add_argument("tests", nargs="*",
                        help="Optional pytest args (default: the whole suite).")
    args = parser.parse_args(argv)

    with contextlib.suppress(AttributeError, OSError):
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")

    try:
        return _run(args)
    except SystemExit:
        raise
    except Exception:  # noqa: BLE001 - the exit status is the point
        traceback.print_exc()
        print("the suite baseline itself failed — exit 2, not a finding",
              file=sys.stderr)
        return 2


def _run(args: argparse.Namespace) -> int:
    previous = read_baseline(args.baseline) if not args.update else (
        read_baseline(args.baseline) if args.baseline.exists() else None)

    if not args.baseline.exists() and not args.update:
        print(f"no baseline at {args.baseline} — a missing baseline is not a "
              f"pass. Run with --update to record one.", file=sys.stderr)
        return 2

    print(f"running: {args.tests or ['<whole suite>']}", flush=True)
    returncode, failures, tests_seen, tail = run_suite(args.tests)
    if failures is None:
        print("no JUnit report was produced — this run is not evidence.\n"
              + tail, file=sys.stderr)
        return 2

    if returncode not in (0, 1):
        # 2 interrupted, 3 internal error, 4 usage, 5 no tests collected.
        print(f"suite exit {returncode} is not a test outcome — this run is "
              f"not evidence of anything.\n{tail}", file=sys.stderr)
        return 2

    # A run that says "failed" while the report records no failure is a
    # contradiction, not a clean run. pytest exits 1 for an aborted session and
    # for a crash after junitxml has already written its file — and in both
    # cases the report looks like a pass. Observed three ways: pytest.exit at
    # collection, an exception in pytest_sessionfinish, and os._exit(1) after
    # the write. Against a real baseline this also reported every known
    # failure as "fixed" on a run that measured nothing.
    if returncode == 1 and not failures:
        print("suite exited 1 but the report records no failure — the session "
              "aborted or crashed after the report was written. Not evidence.",
              file=sys.stderr)
        if tail:
            print(tail, file=sys.stderr)
        return 2

    # And a report that contains no tests at all is not a clean run either,
    # whatever the exit status says.
    if tests_seen == 0:
        print("the report contains no testcases — this run measured nothing.",
              file=sys.stderr)
        return 2

    print(f"suite exit {returncode}; {len(failures)} failing "
          f"of {tests_seen} testcase(s)")
    for name in failures:
        print(f"  FAIL  {name}")

    # A flaky entry has to have failed in the run that records it. Accepting a
    # nodeid on trust let an arbitrary test be marked "never a finding" without
    # ever having failed.
    if args.update:
        witnessed = set(failures) | set((previous or {}).get(
            "known_failures", [])) | set((previous or {}).get("flaky", []))
        unfounded = sorted(set(args.mark_flaky) - witnessed)
        if unfounded:
            print(f"--mark-flaky names that did not fail in this run: "
                  f"{unfounded}. A flaky entry needs evidence.", file=sys.stderr)
            return 2
        still_known = [name for name in failures
                       if name not in set(args.mark_flaky)]
        write_baseline(args.baseline, still_known, args.note, previous,
                       flaky=args.mark_flaky)
        print(f"\nrecorded {len(still_known)} known failure(s), "
              f"{len(args.mark_flaky)} flaky -> {args.baseline}")
        return 0

    # A flaky test is reported but is never a finding in either direction: it
    # fails on record and passes on check, which would make the gate both cry
    # wolf and claim fixes that did not happen.
    delta = compare(previous.get("known_failures", []),
                    previous.get("flaky", []), failures)
    new, flaked, fixed = delta["new"], delta["flaked"], delta["fixed"]
    known = set(previous.get("known_failures", []))

    print("\nSUITE BASELINE")
    if flaked:
        print(f"  {len(flaked)} known-flaky test(s) failed this run "
              f"(not a finding): {flaked}")
    if fixed:
        print(f"  {len(fixed)} known failure(s) no longer failing — record "
              f"with --update: {fixed}")
    if not new:
        print(f"  no new failure ({len(known)} known)")
        return 0

    for name in new:
        print(f"  NEW FAILURE  {name}")
    if args.allow:
        # `--mark-flaky` used to be dropped here, so `--allow` silently lost it.
        write_baseline(args.baseline, sorted(known | set(new)), args.allow,
                       previous, flaky=args.mark_flaky)
        print(f"  accepted: {args.allow} ({len(new)} new failure(s) recorded)")
        return 0

    print("  A failure not in the baseline is one this change introduced.\n"
          "  Re-run with --allow \"<reason>\" if it is intended.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
