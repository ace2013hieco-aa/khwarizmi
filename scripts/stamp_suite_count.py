# SPDX-License-Identifier: Apache-2.0
"""Stamp the canonical suite-collected count (NUM-1 single source of truth).

Derives the count FROM the suite on this tree — never hand-typed — by
running ``pytest --collect-only`` (no extra ``-q``: ``pyproject.toml``
``addopts`` already supplies ``-q``, and a second ``-q`` suppresses the
summary line) and parsing the ``N tests collected`` summary. The stamped
artifact is ``docs/SUITE-COUNT.md``; live surfaces reference it instead
of carrying hard numbers.

Fail-closed: any collection error, unparseable output, or missing
summary refuses with a non-zero exit and writes nothing, so no count
is ever printed that the suite did not produce on this tree.

Usage (from the repo root)::

    PYTHONPATH=<worktree>/src .venv/Scripts/python.exe scripts/stamp_suite_count.py
    PYTHONPATH=<worktree>/src .venv/Scripts/python.exe scripts/stamp_suite_count.py --check

The script uses the running interpreter (must be the project venv,
Python 3.14) and enforces ``PYTHONPATH`` points at this worktree's
``src`` so the count is measured on this tree, not on an installed
copy. Both sides are normalized (separator style and case) before that
comparison, so the native and forward-slash spellings of the same
directory are accepted while a different tree still refuses.

``--check`` derives the count the same way and compares it to the
stamped artifact WITHOUT writing anything: it exits non-zero when the
stamp is stale (drifted from the live suite) or missing/unparseable, so
a gate can enforce freshness.
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
ARTIFACT = REPO_ROOT / "docs" / "SUITE-COUNT.md"
COLLECT_RE = re.compile(r"(?m)^(\d+) tests? collected")
ARTIFACT_RE = re.compile(r"(?m)^Collected: (\d+)\s*$")


def _norm(path: str) -> str:
    """Canonicalize a path for comparison.

    Collapses separator style, case (Windows), duplicate separators and
    trailing slashes, so ``C:/x/src`` and ``C:\\x\\src`` compare equal
    while a genuinely different directory still differs (F1)."""
    return os.path.normcase(os.path.normpath(path))


def _check_tree() -> None:
    raw_src = str(REPO_ROOT / "src")
    src = _norm(raw_src)
    pythonpath = os.environ.get("PYTHONPATH", "")
    entries = {_norm(p) for p in pythonpath.split(os.pathsep) if p}
    if src not in entries:
        raise SystemExit(
            f"REFUSE: PYTHONPATH must include this tree's src ({raw_src}); "
            f"got PYTHONPATH={pythonpath!r}. "
            "Re-run with PYTHONPATH=<worktree>/src."
        )


def _collect_count() -> tuple[int, str]:
    cmd = [sys.executable, "scripts/run_tests.py", "--collect-only"]
    proc = subprocess.run(
        cmd,
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
    )
    output = (proc.stdout or "") + "\n" + (proc.stderr or "")
    match = COLLECT_RE.search(output)
    if proc.returncode != 0 or match is None:
        raise SystemExit(
            "REFUSE: pytest --collect-only did not produce a parseable "
            f"'N tests collected' summary (exit={proc.returncode}). "
            "Nothing stamped.\n"
            f"--- output tail ---\n{output[-2000:]}"
        )
    return int(match.group(1)), output


def _commit() -> str:
    proc = subprocess.run(
        ["git", "rev-parse", "--short", "HEAD"],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
    )
    return proc.stdout.strip() if proc.returncode == 0 else "unknown"


def _stamped_count() -> int | None:
    """The count currently recorded in the artifact, or None if the
    artifact is missing or carries no parseable ``Collected:`` line."""
    if not ARTIFACT.exists():
        return None
    match = ARTIFACT_RE.search(ARTIFACT.read_text(encoding="utf-8"))
    return int(match.group(1)) if match else None


def _check() -> int:
    """Freshness gate: compare the stamped artifact to a live collect.

    Writes nothing. Non-zero when the stamp is missing, unparseable, or
    stale (drifted from the live suite) — the merge-gate enforcement of
    the single source of truth (F2)."""
    _check_tree()
    live, _ = _collect_count()
    stamped = _stamped_count()
    rel = ARTIFACT.relative_to(REPO_ROOT)
    if stamped is None:
        print(
            f"DRIFT: {rel} is missing or has no parseable 'Collected:' "
            f"line (live collected={live}); re-run stamp_suite_count.py",
            file=sys.stderr,
        )
        return 1
    if stamped != live:
        print(
            f"DRIFT: {rel} says collected={stamped} but the live suite "
            f"collects {live}; re-run stamp_suite_count.py",
            file=sys.stderr,
        )
        return 1
    print(f"OK: {rel} collected={stamped} matches the live collect")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if args == ["--check"]:
        return _check()
    if args:
        raise SystemExit(f"usage: {Path(__file__).name} [--check]")
    _check_tree()
    count, _ = _collect_count()
    stamped = (
        "# Suite collected count (GENERATED — do not hand-edit)\n"
        "\n"
        "This file is stamped by ``scripts/stamp_suite_count.py`` from a\n"
        "live ``pytest --collect-only`` on this tree. It is the single\n"
        "source of truth for the suite size (NUM-1); live surfaces\n"
        "reference it instead of carrying hard numbers.\n"
        "\n"
        f"Collected: {count}\n"
        "\n"
        "## Provenance\n"
        "\n"
        f"- Commit: {_commit()}\n"
        f"- Stamped (UTC): {datetime.now(timezone.utc).isoformat()}\n"
        "- Command: `PYTHONPATH=<worktree>/src python scripts/run_tests.py --collect-only`\n"
        "  (no extra `-q`; `pyproject.toml addopts` already supplies `-q`)\n"
        "\n"
        "License: Apache-2.0 (LICENSE).\n"
    )
    ARTIFACT.write_text(stamped, encoding="utf-8", newline="\n")
    print(f"Stamped {ARTIFACT.relative_to(REPO_ROOT)}: collected={count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
