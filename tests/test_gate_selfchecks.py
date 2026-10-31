"""Self-checks — every gate must be able to fail.

Every other test in this tree asserts that the code under test behaves. These
assert that the **instruments** fail when they should, because a gate that
cannot fail is a report with an exit code.

This file exists because of a third-party audit. Three of the four gates gave a
false pass: a depth ratchet measuring the historical maximum, an invariant suite
testing a different checkout, and a matrix red for reasons unrelated to any new
defect. Each was found by *injecting* a defect and watching, and every injection
was then thrown away — so the repairs could have regressed silently. These are
those injections, kept.

Rules for this file:

- **Never mutate `src/`.** Fixtures are temp trees and temp journals; the real
  package is only ever read.
- **Test the exit code, not the message.** A gate is its exit status; text is
  for humans.
- **Each test names the defect it injects**, so a future reader knows what the
  gate is supposed to catch rather than what it happens to catch.

Exit codes, across all three scripts: **0** clean, **1** a finding, **2** the
gate itself could not run (missing input, internal error). A test that accepts 1
where 2 is right would pass a gate that had crashed.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
BASELINE = ROOT / "docs/CONTRACT-BASELINE.json"


def run(script: str, *args: object) -> subprocess.CompletedProcess[str]:
    """Run a gate as the operator would, and keep its exit status."""
    return subprocess.run(
        [sys.executable, str(SCRIPTS / script), *map(str, args)],
        capture_output=True, text=True, encoding="utf-8",
        errors="replace", timeout=300)


# ── a temp package shaped so `layer_of` sees real layers ────────────────────


def _package(tmp_path: Path) -> Path:
    """A two-layer package root, named `hermes` so layers resolve."""
    root = tmp_path / "hermes"
    (root / "core").mkdir(parents=True)
    (root / "persistence").mkdir(parents=True)
    (root / "core" / "__init__.py").write_text("", encoding="utf-8")
    (root / "persistence" / "__init__.py").write_text("", encoding="utf-8")
    (root / "core" / "x.py").write_text("X = 1\n", encoding="utf-8")
    # One cross-layer import, so the persistence->core *pair* is pinned.
    (root / "persistence" / "a.py").write_text(
        "from hermes.core import x\n\nA = 1\n", encoding="utf-8")
    return root


def _ratchet(root: Path, path: Path) -> None:
    result = run("structure_map.py", "--root", root, "--ratchet", path,
                 "--update", "--note", "self-check fixture")
    assert result.returncode == 0, result.stderr


# ── structure_map ───────────────────────────────────────────────────────────


def test_a_new_module_on_a_pinned_pair_fails(tmp_path: Path) -> None:
    """The F6 hole: the pair was pinned, so a new module reaching across was
    invisible. This is the case the audit used to show it."""
    root = _package(tmp_path)
    ratchet = tmp_path / "r.json"
    _ratchet(root, ratchet)

    (root / "persistence" / "b.py").write_text(
        "from hermes.core import x\n\nB = 1\n", encoding="utf-8")

    result = run("structure_map.py", "--root", root, "--ratchet", ratchet)
    assert result.returncode == 1, result.stdout + result.stderr
    assert "NEW MODULE EDGE" in result.stdout


def test_a_new_cycle_fails(tmp_path: Path) -> None:
    """A second strongly-connected component means two subsystems became one."""
    root = _package(tmp_path)
    ratchet = tmp_path / "r.json"
    _ratchet(root, ratchet)

    (root / "core" / "c.py").write_text(
        "from hermes.persistence import d\n\nC = 1\n", encoding="utf-8")
    (root / "persistence" / "d.py").write_text(
        "from hermes.core import c\n\nD = 1\n", encoding="utf-8")

    result = run("structure_map.py", "--root", root, "--ratchet", ratchet)
    assert result.returncode == 1, result.stdout + result.stderr
    assert "NEW CYCLE" in result.stdout


def test_a_missing_ratchet_is_not_a_pass(tmp_path: Path) -> None:
    """It exited 0 before the audit: a typo in the path disabled the gate."""
    root = _package(tmp_path)
    result = run("structure_map.py", "--root", root,
                 "--ratchet", tmp_path / "absent.json")
    assert result.returncode == 2, result.stdout + result.stderr


def test_a_type_only_import_is_not_coupling(tmp_path: Path) -> None:
    """The inverse direction: a false positive is a gate that cries wolf."""
    root = _package(tmp_path)
    ratchet = tmp_path / "r.json"
    _ratchet(root, ratchet)

    (root / "persistence" / "typed.py").write_text(
        "from typing import TYPE_CHECKING\n\n"
        "if TYPE_CHECKING:\n    from hermes.core import x\n\nT = 1\n",
        encoding="utf-8")

    result = run("structure_map.py", "--root", root, "--ratchet", ratchet)
    assert result.returncode == 0, result.stdout + result.stderr


def test_an_unparseable_file_is_a_finding(tmp_path: Path) -> None:
    """An unparseable module adds no edge, so a silent skip would pass over it."""
    root = _package(tmp_path)
    ratchet = tmp_path / "r.json"
    _ratchet(root, ratchet)

    (root / "core" / "broken.py").write_text("def (:\n", encoding="utf-8")

    result = run("structure_map.py", "--root", root, "--ratchet", ratchet)
    assert result.returncode == 1, result.stdout + result.stderr
    assert "UNPARSEABLE" in result.stdout


def test_a_shadowed_file_is_read(tmp_path: Path) -> None:
    """N1. Two files can map to one module name. Python loads the *package*;
    the map kept the module file, so the package's imports were invisible."""
    root = tmp_path / "hermes"
    (root / "core").mkdir(parents=True)
    (root / "core" / "__init__.py").write_text("", encoding="utf-8")
    (root / "core" / "x.py").write_text("X = 1\n", encoding="utf-8")
    # A package and a module with the same name: `pkg/` and `pkg.py`.
    (root / "pkg").mkdir()
    (root / "pkg" / "__init__.py").write_text("P = 1\n", encoding="utf-8")
    (root / "pkg.py").write_text("P = 2\n", encoding="utf-8")
    ratchet = tmp_path / "r.json"
    _ratchet(root, ratchet)

    # Inject into the package __init__ — the file Python actually loads.
    (root / "pkg" / "__init__.py").write_text(
        "from hermes.core import x\nP = 1\n", encoding="utf-8")

    result = run("structure_map.py", "--root", root, "--ratchet", ratchet)
    assert result.returncode == 1, result.stdout + result.stderr
    assert "NEW" in result.stdout


def test_a_bogus_allow_edge_name_is_rejected(tmp_path: Path) -> None:
    """N2. A name matching nothing moved the ratchet and allowed everything."""
    root = _package(tmp_path)
    ratchet = tmp_path / "r.json"
    _ratchet(root, ratchet)
    (root / "persistence" / "b.py").write_text(
        "from hermes.core import x\n\nB = 1\n", encoding="utf-8")

    result = run("structure_map.py", "--root", root, "--ratchet", ratchet,
                 "--allow-edge", "not.a.real.edge->nowhere")
    assert result.returncode == 2, result.stdout + result.stderr


def test_a_non_dict_ratchet_is_unusable_input(tmp_path: Path) -> None:
    """N3. A list read as 'no ratchet yet' and exited 0."""
    root = _package(tmp_path)
    ratchet = tmp_path / "r.json"
    ratchet.write_text("[]", encoding="utf-8")

    result = run("structure_map.py", "--root", root, "--ratchet", ratchet)
    assert result.returncode == 2, result.stdout + result.stderr


# ── contract_matrix ─────────────────────────────────────────────────────────


def test_a_missing_contract_baseline_is_unusable_input(tmp_path: Path) -> None:
    """Exit 2, not 1. The first version asserted 1, so a crashed gate would
    have satisfied it — the exact confusion the docstring warns about."""
    result = run("contract_matrix.py", "--baseline", tmp_path / "absent.json")
    assert result.returncode == 2, result.stdout + result.stderr


def test_a_trimmed_baseline_reports_a_new_finding(tmp_path: Path) -> None:
    """F4: the gate was permanently red, so a *new* finding was indistinguishable
    from the known ones. Removing one accepted key must make it loud again."""
    if not BASELINE.exists():
        pytest.skip("no contract baseline recorded")
    data = json.loads(BASELINE.read_text(encoding="utf-8"))
    accepted = list(data.get("accepted", []))
    if not accepted:
        pytest.skip("baseline is empty; nothing to trim")

    trimmed = tmp_path / "trimmed.json"
    trimmed.write_text(json.dumps({**data, "accepted": accepted[1:]}),
                       encoding="utf-8")
    result = run("contract_matrix.py", "--baseline", trimmed)
    assert result.returncode == 1, result.stdout + result.stderr
    assert "NEW FINDING" in result.stdout
    assert accepted[0] in result.stdout


def test_the_recorded_baseline_passes() -> None:
    """The other side of F4: known findings must not keep the gate red."""
    if not BASELINE.exists():
        pytest.skip("no contract baseline recorded")
    result = run("contract_matrix.py", "--baseline", BASELINE)
    assert result.returncode == 0, result.stdout + result.stderr


def test_the_scripts_under_test_exist() -> None:
    """A missing subject must fail loudly, not satisfy an exit-code assertion."""
    assert (SCRIPTS / "structure_map.py").exists()
    assert (SCRIPTS / "contract_matrix.py").exists()
