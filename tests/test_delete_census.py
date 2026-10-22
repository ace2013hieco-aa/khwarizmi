"""P3-1 pin — the only DELETEs in src/ release the scheduler lock.

The AGENTS.md invariant is "durable research state is append-only": no
DELETE of tasks/evidence/events may exist. The lock-release DELETE is the
single permitted exception (the legacy writer-lock helper; the Controller
itself releases in place). This pin is structural — it counts call sites
and names files, never line numbers.
"""
from __future__ import annotations

from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src"
EXPECTED_FILE = "hermes/persistence/database.py"


def _delete_sites() -> list[tuple[str, str]]:
    sites: list[tuple[str, str]] = []
    for path in sorted(SRC.rglob("*.py")):
        for line in path.read_text(encoding="utf-8").splitlines():
            if "DELETE FROM" in line:
                sites.append((path.relative_to(SRC).as_posix(), line.strip()))
    return sites


def test_delete_from_is_only_the_scheduler_lock_release() -> None:
    sites = _delete_sites()
    assert len(sites) == 2, sites
    assert {path for path, _ in sites} == {EXPECTED_FILE}, sites
    assert all("DELETE FROM scheduler_lock" in line for _, line in sites), sites
