"""CLEANUP/A3 - pins for ``scripts/check_census.py`` (the certified-census checker).

Proves four things:

- the live tree reproduces every certified figure exactly, and the checker agrees;
- the checker's certified constants *are* the certified figures, so the tool
  cannot be made to pass by editing a constant (figures are fixed; the tool must
  reproduce them - AGENTS.md, ``docs/ARCHITECTURE.md`` 3.10, DG-4 sec 4);
- the derivation rules behave as documented, each isolated by a synthetic fixture:
  AST literal-only counting, docstring/comment exclusion, owner vs participant,
  rollback-only participant, layer attribution, foreign-layer detection, and
  persistence-only import counting at any nesting depth;
- the tool is read-only and stdlib-only, by static inspection of its own source.

Certified figures: 121 executed transaction-control calls; 27 acquisition owners
(persistence 18 / gateway 5 / Controller 4); 1 rollback-only participant; 15
persistence->research import statements.
"""

from __future__ import annotations

import ast
import importlib.util
import pathlib
import subprocess
import sys
from types import ModuleType

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
CHECKER_PATH = REPO_ROOT / "scripts" / "check_census.py"

# The certified figures, repeated here as literals on purpose (see the second
# test): if the checker's constants are ever edited, this file fails loudly.
CERTIFIED_CONTROL_CALLS = 121
CERTIFIED_OWNERS_TOTAL = 27
CERTIFIED_OWNERS_BY_LAYER = {"persistence": 18, "gateway": 5, "controller": 4}
CERTIFIED_ROLLBACK_ONLY_PARTICIPANTS = 1
CERTIFIED_PERSISTENCE_TO_RESEARCH_IMPORTS = 15

STDLIB_ONLY_IMPORTS = {"__future__", "argparse", "ast", "dataclasses", "pathlib", "sys"}
MUTATING_CALLS = {
    "write_text",
    "write_bytes",
    "unlink",
    "remove",
    "rename",
    "replace",
    "mkdir",
    "rmdir",
    "system",
    "popen",
    "run",
    "Popen",
}


def _load_checker() -> ModuleType:
    spec = importlib.util.spec_from_file_location("check_census", CHECKER_PATH)
    assert spec is not None and spec.loader is not None, f"cannot load {CHECKER_PATH}"
    module = importlib.util.module_from_spec(spec)
    # Register before exec: dataclasses resolves class annotations via sys.modules.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


check_census = _load_checker()


def _write(root: pathlib.Path, rel: str, source: str) -> pathlib.Path:
    """Write a synthetic module into a scratch checkout under ``root``."""

    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(source, encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# 1. The live tree
# ---------------------------------------------------------------------------
def test_live_tree_reproduces_every_certified_figure() -> None:
    census = check_census.analyse(REPO_ROOT)

    assert check_census.compare(census) == (), check_census.render(census)
    assert len(census.control_calls) == CERTIFIED_CONTROL_CALLS
    assert census.owner_count == CERTIFIED_OWNERS_TOTAL
    assert census.owner_count_by_layer == CERTIFIED_OWNERS_BY_LAYER
    assert len(census.rollback_only_participants) == CERTIFIED_ROLLBACK_ONLY_PARTICIPANTS
    assert len(census.imports) == CERTIFIED_PERSISTENCE_TO_RESEARCH_IMPORTS
    assert census.foreign_layer_calls == ()


def test_live_tree_owner_partition_matches_the_certified_split() -> None:
    """27 owners = 18 persistence + 5 gateway + 4 Controller, and no others."""

    census = check_census.analyse(REPO_ROOT)

    assert census.owner_count == sum(CERTIFIED_OWNERS_BY_LAYER.values())
    assert {o.layer for o in census.owners} == set(CERTIFIED_OWNERS_BY_LAYER)
    assert census.participants, "the rollback-only participant must be classified"


def test_certified_constants_are_the_certified_figures() -> None:
    """The figures are fixed; the tool must reproduce them, never the reverse."""

    assert check_census.CERTIFIED_CONTROL_CALLS == 121
    assert check_census.CERTIFIED_OWNERS_TOTAL == 27
    assert check_census.CERTIFIED_OWNERS_BY_LAYER == {
        "persistence": 18,
        "gateway": 5,
        "controller": 4,
    }
    assert check_census.CERTIFIED_ROLLBACK_ONLY_PARTICIPANTS == 1
    assert check_census.CERTIFIED_PERSISTENCE_TO_RESEARCH_IMPORTS == 15


def test_cli_passes_on_the_live_tree() -> None:
    proc = subprocess.run(
        [sys.executable, str(CHECKER_PATH)],
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "PASS - every certified figure is reproduced exactly." in proc.stdout


# ---------------------------------------------------------------------------
# 2. Rule-level fixtures (each rule isolated)
# ---------------------------------------------------------------------------
def test_rule_counts_only_executed_literal_control_calls(tmp_path: pathlib.Path) -> None:
    _write(
        tmp_path,
        "src/hermes/research/gateway.py",
        '''
"""Prose mentioning conn.execute("BEGIN IMMEDIATE") must not be counted."""


def plain(cur, sql):
    cur.execute(sql)                       # non-literal: not a control call
    cur.execute(f"BEGIN {sql}")            # f-string: not a literal
    cur.executescript("BEGIN; COMMIT;")    # different method: not `.execute`
    cur.execute("BEGIN IMMEDIATE")         # the only counted call
''',
    )

    census = check_census.analyse(tmp_path)

    assert len(census.control_calls) == 1
    call = census.control_calls[0]
    assert call.statement == "BEGIN IMMEDIATE"
    assert call.owner == "plain"
    assert call.layer == "gateway"


def test_rule_owner_versus_participant(tmp_path: pathlib.Path) -> None:
    _write(
        tmp_path,
        "src/hermes/research/gateway.py",
        '''
def owns(cur):
    cur.execute("BEGIN IMMEDIATE")
    cur.execute("COMMIT")
    cur.execute("ROLLBACK")


def rollback_only(cur):
    cur.execute("ROLLBACK")


def commit_only(cur):
    cur.execute("COMMIT")
''',
    )

    census = check_census.analyse(tmp_path)

    assert [o.name for o in census.owners] == ["owns"]
    assert sorted(p.name for p in census.participants) == ["commit_only", "rollback_only"]
    assert [p.name for p in census.rollback_only_participants] == ["rollback_only"]
    assert sum(o.total for o in census.owners) == 3


def test_rule_class_qualified_owner_names(tmp_path: pathlib.Path) -> None:
    _write(
        tmp_path,
        "src/hermes/persistence/repositories.py",
        '''
class Repo:
    def record(self, cur):
        cur.execute("BEGIN IMMEDIATE")

    class Inner:
        def nested(self, cur):
            cur.execute("BEGIN IMMEDIATE")
''',
    )

    census = check_census.analyse(tmp_path)

    assert sorted(o.name for o in census.owners) == ["Repo.Inner.nested", "Repo.record"]
    assert all(o.layer == "persistence" for o in census.owners)


def test_rule_layer_attribution_and_foreign_detection(tmp_path: pathlib.Path) -> None:
    for rel in (
        "src/hermes/persistence/repositories.py",
        "src/hermes/research/gateway.py",
        "src/hermes/research/controller.py",
    ):
        _write(tmp_path, rel, 'def own(cur):\n    cur.execute("BEGIN")\n')

    census = check_census.analyse(tmp_path)
    assert census.owner_count_by_layer == {"persistence": 1, "gateway": 1, "controller": 1}
    assert census.foreign_layer_calls == ()

    _write(tmp_path, "src/hermes/research/elsewhere.py", 'def stray(cur):\n    cur.execute("COMMIT")\n')
    stray = check_census.analyse(tmp_path)

    assert [c.path for c in stray.foreign_layer_calls] == ["src/hermes/research/elsewhere.py"]
    figures = {d.figure for d in check_census.compare(stray)}
    assert "control calls outside the certified layers" in figures


def test_rule_counts_only_persistence_to_research_imports(tmp_path: pathlib.Path) -> None:
    _write(
        tmp_path,
        "src/hermes/persistence/repositories.py",
        '''
import hermes.core.events
from hermes.research.claims import claim_id_of
from hermes.persistence.database import connect


def lazy():
    from hermes.research.programs import program_id_of
    import hermes.tools.providers

    return program_id_of, claim_id_of, connect
''',
    )
    _write(
        tmp_path,
        "src/hermes/research/gateway.py",
        "from hermes.research.claims import claim_id_of\n",
    )

    census = check_census.analyse(tmp_path)

    assert len(census.imports) == 2
    assert [i.module for i in census.imports] == [
        "hermes.research.claims",
        "hermes.research.programs",
    ]


def test_rule_reports_failures_instead_of_adjusting_figures(tmp_path: pathlib.Path) -> None:
    """An empty tree can never satisfy the figures: compare() must complain."""

    census = check_census.analyse(tmp_path)

    assert len(census.control_calls) == 0
    figures = {d.figure for d in check_census.compare(census)}
    assert "executed transaction-control calls" in figures
    assert "acquisition owners (total)" in figures
    assert "persistence->research import statements" in figures
    assert "PASS" not in check_census.render(census)
    assert "FAIL" in check_census.render(census)


# ---------------------------------------------------------------------------
# 3. The tool's own constraints
# ---------------------------------------------------------------------------
def test_tool_is_read_only_and_stdlib_only() -> None:
    source = CHECKER_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source)

    imported: set[str] = set()
    offenders: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
        elif isinstance(node, ast.Call):
            name = None
            if isinstance(node.func, ast.Attribute):
                name = node.func.attr
            elif isinstance(node.func, ast.Name):
                name = node.func.id
            if name in MUTATING_CALLS:
                offenders.append(f"{name} at line {node.lineno}")

    outside = sorted(imported - STDLIB_ONLY_IMPORTS)
    assert not outside, f"non-stdlib imports: {outside}"
    assert not offenders, f"read-only violation: {offenders}"
    assert "\u2192" not in source, "checker output must stay ASCII for the Windows console"
