"""Depth self-checks — the ratchet must be able to fail.

Split from `test_gate_selfchecks.py` deliberately. That file travelled with the
contract matrix into a slice whose closure excluded the depth ratchet, and five
of its tests failed on a tree without the script — while
`test_a_missing_depth_baseline_is_not_a_pass` *passed*, because a missing script
makes Python exit 2 and that is exactly what it asserted. A test that passes
when its subject is absent is the defect these files exist to catch.

So: one file per instrument, merged with the instrument it tests.

Exit codes: 0 clean, 1 a finding, 2 the gate could not run.
"""
from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
from pathlib import Path
from typing import Sequence

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"


def run(script: str, *args: object) -> subprocess.CompletedProcess[str]:
    """Run a gate as the operator would, and keep its exit status."""
    return subprocess.run(
        [sys.executable, str(SCRIPTS / script), *map(str, args)],
        capture_output=True, text=True, encoding="utf-8",
        errors="replace", timeout=300)


# ── depth_regression ────────────────────────────────────────────────────────


def _journal(path: Path, rows: Sequence[tuple[str, int, str]]) -> Path:
    """A minimal journal: (project, stages_recorded, stage_reached) per event."""
    path.unlink(missing_ok=True)   # reused paths must start empty
    conn = sqlite3.connect(path)
    conn.execute(
        "create table events (event_id integer primary key autoincrement, "
        "event_type text, project_id text, to_state text, reason text, "
        "payload_json text)")
    for project, depth, stage in rows:
        conn.execute(
            "insert into events (event_type, project_id, to_state, reason, "
            "payload_json) values ('TaskStatusChanged', ?, 'FAILED', 'x', ?)",
            (project, json.dumps({"stages_recorded": depth,
                                  "stages_declared": 9,
                                  "stage_reached": stage})))
    conn.commit()
    conn.close()
    return path


def _baseline(path: Path, depth: int, stage: str) -> Path:
    path.write_text(json.dumps({
        "ratchet": {"depth": depth, "stage": stage, "project": "p"},
        "history": []}), encoding="utf-8")
    return path


def test_a_shallower_later_run_fails(tmp_path: Path) -> None:
    """F1, the false pass. The journal is append-only, so reading the maximum
    ever recorded meant a later, shallower run could never lower the number."""
    db = _journal(tmp_path / "j.db", [("p", 3, "PREDICTION"), ("p", 1, "QUESTION")])
    base = _baseline(tmp_path / "b.json", 3, "PREDICTION")

    result = run("depth_regression.py", "--db", db, "--baseline", base)
    assert result.returncode == 1, result.stdout + result.stderr
    assert "REACH FELL" in result.stdout


def test_a_regressed_project_is_not_masked_by_a_deeper_sibling(
        tmp_path: Path) -> None:
    """The neighbouring case of F1. The first repair compared the global
    maximum, so A going 3 -> 1 passed because B was still at 3."""
    db = _journal(tmp_path / "j.db", [("a", 3, "PREDICTION"),
                                      ("b", 3, "PREDICTION")])
    base = tmp_path / "b.json"
    result = run("depth_regression.py", "--db", db, "--baseline", base,
                 "--update", "--note", "two projects at 3")
    assert result.returncode == 0, result.stderr

    conn = sqlite3.connect(db)
    conn.execute(
        "insert into events (event_type, project_id, to_state, reason, "
        "payload_json) values ('TaskStatusChanged', 'a', 'FAILED', 'x', ?)",
        (json.dumps({"stages_recorded": 1, "stage_reached": "QUESTION"}),))
    conn.commit()
    conn.close()

    result = run("depth_regression.py", "--db", db, "--baseline", base)
    assert result.returncode == 1, result.stdout + result.stderr
    assert "PROJECT REGRESSED a" in result.stdout


def test_a_project_the_baseline_tracks_but_the_journal_does_not(
        tmp_path: Path) -> None:
    """N4. An absent project was treated as 'not regressed'."""
    db = _journal(tmp_path / "j.db", [("a", 3, "PREDICTION"),
                                      ("b", 3, "PREDICTION")])
    base = tmp_path / "b.json"
    assert run("depth_regression.py", "--db", db, "--baseline", base,
               "--update", "--note", "a and b at 3").returncode == 0

    _journal(db, [("b", 3, "PREDICTION")])   # `a` disappears
    result = run("depth_regression.py", "--db", db, "--baseline", base)
    assert result.returncode == 1, result.stdout + result.stderr
    assert "PROJECT NOT MEASURED a" in result.stdout


def test_a_bare_update_cannot_launder_a_project_regression(
        tmp_path: Path) -> None:
    """N5. --update demanded a reason only when the *global* depth fell."""
    db = _journal(tmp_path / "j.db", [("a", 3, "PREDICTION"),
                                      ("b", 3, "PREDICTION")])
    base = tmp_path / "b.json"
    assert run("depth_regression.py", "--db", db, "--baseline", base,
               "--update", "--note", "a and b at 3").returncode == 0

    conn = sqlite3.connect(db)
    conn.execute(
        "insert into events (event_type, project_id, to_state, reason, "
        "payload_json) values ('TaskStatusChanged', 'a', 'FAILED', 'x', ?)",
        (json.dumps({"stages_recorded": 1, "stage_reached": "QUESTION"}),))
    conn.commit()
    conn.close()

    result = run("depth_regression.py", "--db", db, "--baseline", base,
                 "--update")
    assert result.returncode == 1, result.stdout + result.stderr


def test_a_missing_depth_baseline_is_not_a_pass(tmp_path: Path) -> None:
    db = _journal(tmp_path / "j.db", [("p", 1, "QUESTION")])
    result = run("depth_regression.py", "--db", db,
                 "--baseline", tmp_path / "absent.json")
    assert result.returncode == 2, result.stdout + result.stderr


def test_an_unmeasurable_journal_is_not_a_pass(tmp_path: Path) -> None:
    """No field-bearing event means the question cannot be answered. Reporting
    0 would claim a depth nobody measured."""
    db = tmp_path / "empty.db"
    conn = sqlite3.connect(db)
    conn.execute(
        "create table events (event_id integer primary key autoincrement, "
        "event_type text, project_id text, to_state text, reason text, "
        "payload_json text)")
    conn.execute("insert into events (event_type, project_id, payload_json) "
                 "values ('TaskStatusChanged', 'p', '{}')")
    conn.commit()
    conn.close()
    base = _baseline(tmp_path / "b.json", 0, "QUESTION")

    result = run("depth_regression.py", "--db", db, "--baseline", base)
    assert result.returncode == 1, result.stdout + result.stderr
    assert "UNMEASURABLE" in result.stdout




def test_the_script_under_test_exists() -> None:
    """A missing subject must fail loudly, not satisfy an exit-code assertion."""
    assert (SCRIPTS / "depth_regression.py").exists()
