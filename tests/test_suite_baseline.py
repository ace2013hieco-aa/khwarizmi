"""Suite-baseline self-checks — the gate must fail when it should, and not lie.

One file per instrument, merged with the instrument it tests.

The comparison is pure, so it is tested directly. The plumbing is exercised
**in-process** with `run_suite` monkeypatched, deliberately: the first version
spawned `suite_baseline` from these tests, which spawned the runner, which ran
this file again — recursion, and under the full suite it failed for that reason
rather than for any defect. Monkeypatching also makes the failure path testable
on a machine that has no reliably-failing test to point at.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"

sys.path.insert(0, str(SCRIPTS))
import suite_baseline  # noqa: E402  # pyright: ignore[reportMissingImports]


def test_the_script_under_test_exists() -> None:
    assert (SCRIPTS / "suite_baseline.py").exists()


# ── the comparison, directly ────────────────────────────────────────────────


def test_a_failure_the_baseline_does_not_know_is_new() -> None:
    delta = suite_baseline.compare(known=["a"], flaky=[], failures=["a", "b"])
    assert delta["new"] == ["b"]
    assert delta["fixed"] == []


def test_a_known_failure_that_stopped_failing_is_fixed() -> None:
    delta = suite_baseline.compare(known=["a", "b"], flaky=[], failures=["a"])
    assert delta["new"] == []
    assert delta["fixed"] == ["b"]


def test_a_flaky_failure_gates_in_neither_direction() -> None:
    """It fails on record and passes on check. As `known` the gate would claim a
    fix it did not make; as unknown it would cry wolf every other run."""
    delta = suite_baseline.compare(known=[], flaky=["f"], failures=["f"])
    assert delta["new"] == []
    assert delta["fixed"] == []
    assert delta["flaked"] == ["f"]

    delta = suite_baseline.compare(known=[], flaky=["f"], failures=[])
    assert delta["new"] == []
    assert delta["fixed"] == []


def test_a_clean_run_against_a_baseline_is_silent() -> None:
    delta = suite_baseline.compare(known=["a"], flaky=["f"], failures=["a"])
    assert delta == {"new": [], "flaked": [], "fixed": []}


# ── the plumbing, in-process ────────────────────────────────────────────────


def test_a_missing_baseline_is_not_a_pass(tmp_path: Path) -> None:
    assert suite_baseline.main(
        ["--baseline", str(tmp_path / "absent.json")]) == 2


def test_a_run_that_collected_nothing_is_not_evidence(
        tmp_path: Path, monkeypatch) -> None:
    """pytest exits 5 for "no tests collected" with zero failures. A tool that
    reads that as clean would pass every gate forever."""
    baseline = tmp_path / "b.json"
    suite_baseline.write_baseline(baseline, [], "seed", None)
    monkeypatch.setattr(suite_baseline, "run_suite",
                        lambda extra: (5, [], 0, "no tests ran"))
    assert suite_baseline.main(["--baseline", str(baseline)]) == 2


def test_a_new_failure_exits_one(tmp_path: Path, monkeypatch) -> None:
    baseline = tmp_path / "b.json"
    suite_baseline.write_baseline(baseline, ["tests/x.py::test_a"], "seed", None)
    monkeypatch.setattr(suite_baseline, "run_suite",
                        lambda extra: (1, ["tests/y.py::test_b"], 10, ""))
    assert suite_baseline.main(["--baseline", str(baseline)]) == 1


def test_a_known_failure_alone_exits_zero(tmp_path: Path, monkeypatch) -> None:
    baseline = tmp_path / "b.json"
    suite_baseline.write_baseline(baseline, ["tests/x.py::test_a"], "seed", None)
    monkeypatch.setattr(suite_baseline, "run_suite",
                        lambda extra: (1, ["tests/x.py::test_a"], 10, ""))
    assert suite_baseline.main(["--baseline", str(baseline)]) == 0


def test_a_flaky_failure_alone_exits_zero(tmp_path: Path, monkeypatch) -> None:
    baseline = tmp_path / "b.json"
    suite_baseline.write_baseline(baseline, [], "seed", None,
                                  flaky=["tests/x.py::test_f"])
    monkeypatch.setattr(suite_baseline, "run_suite",
                        lambda extra: (1, ["tests/x.py::test_f"], 10, ""))
    assert suite_baseline.main(["--baseline", str(baseline)]) == 0


# ── the redteam's findings, as permanent checks ─────────────────────────────


def test_exit_one_with_no_recorded_failure_is_not_evidence(
        tmp_path: Path, monkeypatch) -> None:
    """H1. pytest exits 1 for an aborted session and for a crash after junitxml
    wrote — the report looks like a pass. Against a real baseline this also
    reported every known failure as 'fixed' on a run that measured nothing."""
    baseline = tmp_path / "b.json"
    suite_baseline.write_baseline(baseline, ["tests/x.py::test_a"], "seed", None)
    monkeypatch.setattr(suite_baseline, "run_suite",
                        lambda extra: (1, [], 0, "traceback..."))
    assert suite_baseline.main(["--baseline", str(baseline)]) == 2


def test_a_report_with_no_testcases_is_not_evidence(
        tmp_path: Path, monkeypatch) -> None:
    """Even at exit 0: a run that collected nothing measured nothing."""
    baseline = tmp_path / "b.json"
    suite_baseline.write_baseline(baseline, ["tests/x.py::test_a"], "seed", None)
    monkeypatch.setattr(suite_baseline, "run_suite",
                        lambda extra: (0, [], 0, ""))
    assert suite_baseline.main(["--baseline", str(baseline)]) == 2


def test_mark_flaky_needs_evidence(tmp_path: Path, monkeypatch) -> None:
    """H4. An arbitrary nodeid could be marked 'never a finding' without ever
    having failed."""
    baseline = tmp_path / "b.json"
    suite_baseline.write_baseline(baseline, [], "seed", None)
    monkeypatch.setattr(suite_baseline, "run_suite",
                        lambda extra: (1, ["tests/x.py::test_a"], 10, ""))
    assert suite_baseline.main(
        ["--baseline", str(baseline), "--update",
         "--mark-flaky", "tests/x.py::never_failed"]) == 2


def test_nodeid_keeps_the_class_even_when_file_is_present() -> None:
    """H5. Preferring `file` dropped the class, and the suite has six
    (file, leaf-name) pairs across classes — under xunit1 a swapped failure
    became invisible.

    The classname names a **real** module on purpose: the first version of this
    test pointed at a fictional `tests/test_dup.py`, so `_nodeid` could not
    resolve the module and fell back to the dotted classname. The assertion then
    failed for the fixture's sake, not the code's — a test that was wrong about
    what it was testing.
    """
    import xml.etree.ElementTree as ET

    case = ET.Element("testcase", {
        "file": "tests/test_suite_baseline.py",
        "classname": "tests.test_suite_baseline.TestFake",
        "name": "test_same"})
    assert suite_baseline._nodeid(case) == \
        "tests/test_suite_baseline.py::TestFake::test_same"


def test_nodeid_falls_back_to_classname_when_no_module_matches() -> None:
    """And when it cannot resolve a module, the dotted classname is still a
    unique, stable key — worse than a path, better than colliding."""
    import xml.etree.ElementTree as ET

    case = ET.Element("testcase", {
        "classname": "tests.no_such_module.TestBeta",
        "name": "test_same"})
    assert suite_baseline._nodeid(case) == \
        "tests.no_such_module.TestBeta::test_same"


def test_marking_flaky_removes_it_from_known(
        tmp_path: Path, monkeypatch) -> None:
    """A flaky test is not a known failure. Recording it in both made the gate
    report it as 'fixed' on every run where it passed."""
    import json

    baseline = tmp_path / "b.json"
    suite_baseline.write_baseline(baseline, [], "seed", None)
    monkeypatch.setattr(suite_baseline, "run_suite",
                        lambda extra: (1, ["tests/x.py::test_a"], 10, ""))
    assert suite_baseline.main(
        ["--baseline", str(baseline), "--update",
         "--mark-flaky", "tests/x.py::test_a"]) == 0
    data = json.loads(baseline.read_text(encoding="utf-8"))
    assert data["known_failures"] == []
    assert data["flaky"] == ["tests/x.py::test_a"]


def test_a_previous_known_failure_can_be_marked_flaky_while_passing(
        tmp_path: Path, monkeypatch) -> None:
    """The evidence rule was too strict: a flaky test passes precisely when you
    try to record it, so requiring a failure *in that run* made it
    unrecordable. History counts as evidence."""
    import json

    baseline = tmp_path / "b.json"
    suite_baseline.write_baseline(baseline, ["tests/x.py::test_a"], "seed", None)
    monkeypatch.setattr(suite_baseline, "run_suite",
                        lambda extra: (0, [], 10, ""))
    assert suite_baseline.main(
        ["--baseline", str(baseline), "--update",
         "--mark-flaky", "tests/x.py::test_a"]) == 0
    data = json.loads(baseline.read_text(encoding="utf-8"))
    assert data["flaky"] == ["tests/x.py::test_a"]

