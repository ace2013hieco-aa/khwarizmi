"""RETRACTION-DEMO wrapper: the replayable cone demo must exit 0.

``scripts/demo_retraction_cone.py`` is the offline, self-verifying walk
through the S5 source-retraction cone (retract a source -> invalidate the
downstream dependency cone -> supersede the contradiction the retraction
reached -> refuse a fresh citation of the retracted evidence).

The demo carries its own 40-check ledger and its own exit-code contract
(0 = every check passed, 1 = a check failed, 2 = it raised). This test
runs it in a SUBPROCESS - the demo owns an in-memory database and a
frozen clock, so nothing here reads or writes the suite's state - and
pins three things: the exit status, the absence of any ``[FAIL]`` line,
and the presence of the load-bearing observations, so a demo that
"passes" without actually retracting anything fails the suite.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "demo_retraction_cone.py"
TIMEOUT_SECONDS = 120

# The observations that prove the demo reached the end of the mechanism,
# not just its first beat.
REQUIRED_LINES = (
    "[PASS] ratified retraction admitted",
    "[PASS] the two-hop memo is in the cone (transitive)",
    "[PASS] cone_digest recomputes from persisted state",
    "[PASS] contradiction cx_",          # prefix: the id is content-derived
    "[PASS] the fresh classification is refused",
    "RESULT:",
    "EXIT 0",
)


def test_retraction_demo_replays_green() -> None:
    proc = subprocess.run(
        [sys.executable, str(SCRIPT)],
        capture_output=True, text=True, encoding="utf-8",
        errors="replace", timeout=TIMEOUT_SECONDS, cwd=str(REPO_ROOT),
        check=False)
    output = proc.stdout + proc.stderr
    assert proc.returncode == 0, (
        f"demo exit status {proc.returncode}; last output:\n"
        f"{output[-4000:]}")
    assert "[FAIL]" not in output, f"the demo reported a failure:\n{output}"
    for line in REQUIRED_LINES:
        assert line in output, f"missing observation {line!r} in:\n{output}"


def test_retraction_demo_is_replayable_from_another_directory(
        tmp_path: Path) -> None:
    """The demo resolves its own paths, so a judge can run it from
    anywhere with no arguments (the offline-replay requirement)."""
    proc = subprocess.run(
        [sys.executable, str(SCRIPT)],
        capture_output=True, text=True, encoding="utf-8",
        errors="replace", timeout=TIMEOUT_SECONDS, cwd=str(tmp_path),
        check=False)
    assert proc.returncode == 0, (
        f"demo failed from {tmp_path}; last output:\n"
        f"{(proc.stdout + proc.stderr)[-4000:]}")
    assert "EXIT 0" in proc.stdout
