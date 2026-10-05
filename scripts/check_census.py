"""scripts/check_census.py - certified-census checker (read-only, stdlib-only).

Re-derives the three physical census figures the architecture certifies and
compares them against the certified constants below. It never adjusts a
figure: if the tree does not reproduce them, it reports FAIL and exits 1.

Certified figures and their sources (all at ``main``):

- ``121`` executed transaction-control calls, ``27`` acquisition owners
  (persistence 18 / gateway 5 / Controller 4) plus ``1`` rollback-only
  participant - ``AGENTS.md`` ("27 acquisition owners across persistence (18),
  gateway (5), and Controller (4), plus one rollback-only participant"), and
  ``docs/ARCHITECTURE.md`` 3.10 ("121 executed transaction-control calls held
  by 27 acquisition owners plus one rollback-only participant").
- ``15`` persistence->research import statements - ``AGENTS.md`` (Change
  discipline) and ``docs/ARCHITECTURE.md`` 3.10 ("A bounded set of
  persistence->research runtime dependencies (15 import statements) remains").

Derivation method (DG-4 sec 4, ``docs/archive/HERMES_DG4_REPOSITORY_STRUCTURAL_
DESIGN_GATE_2026-09-21.md``; re-run in DG-6 sec 5):

1. **Control-call rule** - an *executed* call ``<expr>.execute(<string
   literal>)`` whose literal, stripped and upper-cased, starts with ``BEGIN``,
   ``COMMIT``, ``ROLLBACK``, ``SAVEPOINT`` or ``RELEASE``. Derived from the
   AST, so docstring and comment prose is excluded by construction.
2. **Owner rule** - the enclosing function (class-qualified) of at least one
   *acquisition* call (``BEGIN``/``SAVEPOINT``) is an acquisition owner. A
   function that issues control calls but acquires nothing is a *participant*,
   not an owner; a participant whose only calls are ``ROLLBACK`` is a
   rollback-only participant.
3. **Layer rule** - owners are attributed by file: ``src/hermes/persistence/``
   -> persistence, ``src/hermes/research/gateway.py`` -> gateway,
   ``src/hermes/research/controller.py`` -> Controller. Control calls anywhere
   else are reported separately and fail the check, because the certified
   census has no other owner.
4. **Import rule** - every ``import``/``from`` statement inside
   ``src/hermes/persistence/`` whose target module is ``hermes.research`` or a
   submodule of it, at any nesting depth (module level or lazy/function level);
   each statement counts once.

The tool only reads: it opens no file for writing and creates nothing.

Usage:
    python scripts/check_census.py [--repo-root PATH] [--verbose]

Exit status: 0 when every certified figure is reproduced, 1 otherwise.
"""

from __future__ import annotations

import argparse
import ast
import dataclasses
import pathlib
import sys

# --------------------------------------------------------------------------
# Certified figures. These are the contract. Never edit one to make the tool
# pass: the tree must reproduce them (AGENTS.md; docs/ARCHITECTURE.md 3.10).
# --------------------------------------------------------------------------
CERTIFIED_CONTROL_CALLS = 121
CERTIFIED_OWNERS_TOTAL = 27
CERTIFIED_OWNERS_BY_LAYER = {"persistence": 18, "gateway": 5, "controller": 4}
CERTIFIED_ROLLBACK_ONLY_PARTICIPANTS = 1
CERTIFIED_PERSISTENCE_TO_RESEARCH_IMPORTS = 15

CONTROL_PREFIXES = ("BEGIN", "COMMIT", "ROLLBACK", "SAVEPOINT", "RELEASE")
ACQUISITION_PREFIXES = ("BEGIN", "SAVEPOINT")

PERSISTENCE_PREFIX = "src/hermes/persistence/"
GATEWAY_PATH = "src/hermes/research/gateway.py"
CONTROLLER_PATH = "src/hermes/research/controller.py"

RESEARCH_PACKAGE = "hermes.research"

SOURCE_ROOT = "src/hermes"


# --------------------------------------------------------------------------
# Analysis (pure, read-only)
# --------------------------------------------------------------------------
@dataclasses.dataclass(frozen=True)
class ControlCall:
    """One executed transaction-control call."""

    path: str
    lineno: int
    statement: str
    owner: str
    layer: str


@dataclasses.dataclass(frozen=True)
class ImportSite:
    """One persistence->research import statement."""

    path: str
    lineno: int
    module: str


@dataclasses.dataclass(frozen=True)
class Owner:
    """An enclosing function that issues transaction-control calls."""

    name: str
    layer: str
    path: str
    begin: int
    commit: int
    rollback: int
    other: int

    @property
    def acquisitions(self) -> int:
        return self.begin

    @property
    def total(self) -> int:
        return self.begin + self.commit + self.rollback + self.other


@dataclasses.dataclass(frozen=True)
class Census:
    """The measured census, plus the details a FAIL has to explain."""

    control_calls: tuple[ControlCall, ...]
    owners: tuple[Owner, ...]
    participants: tuple[Owner, ...]
    imports: tuple[ImportSite, ...]

    @property
    def owner_count(self) -> int:
        return len(self.owners)

    @property
    def owner_count_by_layer(self) -> dict[str, int]:
        counts: dict[str, int] = dict.fromkeys(CERTIFIED_OWNERS_BY_LAYER, 0)
        for owner in self.owners:
            counts[owner.layer] = counts.get(owner.layer, 0) + 1
        return counts

    @property
    def rollback_only_participants(self) -> tuple[Owner, ...]:
        return tuple(
            p
            for p in self.participants
            if p.rollback > 0 and p.begin == 0 and p.commit == 0 and p.other == 0
        )

    @property
    def calls_by_prefix(self) -> dict[str, int]:
        counts: dict[str, int] = dict.fromkeys(CONTROL_PREFIXES, 0)
        for call in self.control_calls:
            head = call.statement.strip().upper().split()[0]
            counts[head] = counts.get(head, 0) + 1
        return counts

    @property
    def foreign_layer_calls(self) -> tuple[ControlCall, ...]:
        """Control calls outside the three certified owner layers."""

        return tuple(c for c in self.control_calls if c.layer not in CERTIFIED_OWNERS_BY_LAYER)


def _head_of(value: str) -> str:
    return value.strip().upper().split(maxsplit=1)[0] if value.strip() else ""


def _is_control_literal(value: str) -> bool:
    return _head_of(value) in CONTROL_PREFIXES


def _control_literal_of(node: ast.Call) -> str | None:
    """Return the control statement of an ``.execute(<literal>)`` call, else None.

    A non-literal first argument (a variable, an f-string, a concatenation) is
    not an executed literal control call and is deliberately ignored.
    """

    if not node.args:
        return None
    first = node.args[0]
    if (
        isinstance(first, ast.Constant)
        and isinstance(first.value, str)
        and _is_control_literal(first.value)
    ):
        return first.value.strip().upper()
    return None


def _owner_scope(scope: tuple[str, ...]) -> str:
    return ".".join(scope) if scope else "<module>"


def _module_targets_research(module: str | None) -> bool:
    if not module:
        return False
    return module == RESEARCH_PACKAGE or module.startswith(RESEARCH_PACKAGE + ".")


def layer_of(rel_path: str) -> str:
    """Attribute a source path to one of the three certified owner layers."""

    if rel_path.startswith(PERSISTENCE_PREFIX):
        return "persistence"
    if rel_path == GATEWAY_PATH:
        return "gateway"
    if rel_path == CONTROLLER_PATH:
        return "controller"
    return "other"


class _ModuleCensus(ast.NodeVisitor):
    """Collect control calls and research imports from one module."""

    def __init__(self, rel_path: str) -> None:
        self.rel_path = rel_path
        self.layer = layer_of(rel_path)
        self._scope: list[str] = []
        self.calls: list[ControlCall] = []
        self.imports: list[ImportSite] = []

    # -- scope tracking ---------------------------------------------------
    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self._scope.append(node.name)
        self.generic_visit(node)
        self._scope.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._scope.append(node.name)
        self.generic_visit(node)
        self._scope.pop()

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._scope.append(node.name)
        self.generic_visit(node)
        self._scope.pop()

    # -- imports ----------------------------------------------------------
    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        if self.rel_path.startswith(PERSISTENCE_PREFIX) and _module_targets_research(node.module):
            self.imports.append(ImportSite(self.rel_path, node.lineno, node.module or ""))
        self.generic_visit(node)

    def visit_Import(self, node: ast.Import) -> None:
        if self.rel_path.startswith(PERSISTENCE_PREFIX):
            for alias in node.names:
                if _module_targets_research(alias.name):
                    self.imports.append(ImportSite(self.rel_path, node.lineno, alias.name))
                    break
        self.generic_visit(node)

    # -- control calls ----------------------------------------------------
    def visit_Call(self, node: ast.Call) -> None:
        func = node.func
        statement = _control_literal_of(node)
        if isinstance(func, ast.Attribute) and func.attr == "execute" and statement is not None:
            self.calls.append(
                ControlCall(
                    path=self.rel_path,
                    lineno=node.lineno,
                    statement=statement,
                    owner=_owner_scope(tuple(self._scope)),
                    layer=self.layer,
                )
            )
        self.generic_visit(node)


def _build_owners(calls: tuple[ControlCall, ...]) -> tuple[tuple[Owner, ...], tuple[Owner, ...]]:
    """Fold control calls into owners (>=1 acquisition) and participants."""

    buckets: dict[tuple[str, str, str], dict[str, int]] = {}
    for call in calls:
        key = (call.layer, call.path, call.owner)
        slot = buckets.setdefault(key, {"BEGIN": 0, "COMMIT": 0, "ROLLBACK": 0, "other": 0})
        head = _head_of(call.statement)
        if head in ("BEGIN", "SAVEPOINT"):
            slot["BEGIN"] += 1
        elif head == "COMMIT":
            slot["COMMIT"] += 1
        elif head == "ROLLBACK":
            slot["ROLLBACK"] += 1
        else:
            slot["other"] += 1
    owners: list[Owner] = []
    participants: list[Owner] = []
    for (layer, path, name), slot in buckets.items():
        owner = Owner(
            name=name,
            layer=layer,
            path=path,
            begin=slot["BEGIN"],
            commit=slot["COMMIT"],
            rollback=slot["ROLLBACK"],
            other=slot["other"],
        )
        (owners if owner.acquisitions > 0 else participants).append(owner)
    owners.sort(key=lambda o: (o.layer, o.path, o.name))
    participants.sort(key=lambda o: (o.layer, o.path, o.name))
    return tuple(owners), tuple(participants)


def analyse(repo_root: pathlib.Path) -> Census:
    """Measure the census on a checkout. Pure: reads source, writes nothing."""

    source_root = repo_root / SOURCE_ROOT
    calls: list[ControlCall] = []
    imports: list[ImportSite] = []
    for path in sorted(source_root.rglob("*.py")):
        rel = path.relative_to(repo_root).as_posix()
        census = _ModuleCensus(rel)
        census.visit(ast.parse(path.read_text(encoding="utf-8"), filename=str(path)))
        calls.extend(census.calls)
        imports.extend(census.imports)
    owners, participants = _build_owners(tuple(calls))
    calls.sort(key=lambda c: (c.path, c.lineno))
    imports.sort(key=lambda i: (i.path, i.lineno))
    return Census(
        control_calls=tuple(calls),
        owners=owners,
        participants=participants,
        imports=tuple(imports),
    )


# --------------------------------------------------------------------------
# Reporting
# --------------------------------------------------------------------------
@dataclasses.dataclass(frozen=True)
class Discrepancy:
    """One certified figure that the tree does not reproduce."""

    figure: str
    expected: int
    actual: int
    detail: str = ""


def compare(census: Census) -> tuple[Discrepancy, ...]:
    """Compare a measurement against the certified figures. Order is stable."""

    out: list[Discrepancy] = []
    by_layer = census.owner_count_by_layer

    if len(census.control_calls) != CERTIFIED_CONTROL_CALLS:
        out.append(
            Discrepancy(
                "executed transaction-control calls",
                CERTIFIED_CONTROL_CALLS,
                len(census.control_calls),
                _sample(census.control_calls),
            )
        )
    for layer, expected in CERTIFIED_OWNERS_BY_LAYER.items():
        actual = by_layer.get(layer, 0)
        if actual != expected:
            out.append(
                Discrepancy(
                    f"acquisition owners ({layer})",
                    expected,
                    actual,
                    _owner_sample(census, layer),
                )
            )
    if census.owner_count != CERTIFIED_OWNERS_TOTAL:
        out.append(
            Discrepancy(
                "acquisition owners (total)",
                CERTIFIED_OWNERS_TOTAL,
                census.owner_count,
                _owner_sample(census, None),
            )
        )
    rollback_only = census.rollback_only_participants
    if len(rollback_only) != CERTIFIED_ROLLBACK_ONLY_PARTICIPANTS:
        out.append(
            Discrepancy(
                "rollback-only participants",
                CERTIFIED_ROLLBACK_ONLY_PARTICIPANTS,
                len(rollback_only),
                "observed: "
                + ", ".join(f"{p.path}:{p.name}" for p in rollback_only)
                if rollback_only
                else "observed: none",
            )
        )
    if len(census.imports) != CERTIFIED_PERSISTENCE_TO_RESEARCH_IMPORTS:
        out.append(
            Discrepancy(
                "persistence->research import statements",
                CERTIFIED_PERSISTENCE_TO_RESEARCH_IMPORTS,
                len(census.imports),
                _import_sample(census),
            )
        )
    foreign = census.foreign_layer_calls
    if foreign:
        out.append(
            Discrepancy(
                "control calls outside the certified layers",
                0,
                len(foreign),
                _sample(foreign),
            )
        )
    return tuple(out)


def _sample(calls: tuple[ControlCall, ...], limit: int = 6) -> str:
    shown = ", ".join(f"{c.path}:{c.lineno} {c.statement}" for c in calls[:limit])
    if len(calls) > limit:
        shown += f", ... (+{len(calls) - limit})"
    return shown


def _owner_sample(census: Census, layer: str | None) -> str:
    names = [
        f"{o.layer}:{o.path}:{o.name} ({o.begin}B/{o.commit}C/{o.rollback}R)"
        for o in census.owners
        if layer is None or o.layer == layer
    ]
    return " | ".join(names)


def _import_sample(census: Census) -> str:
    return ", ".join(f"{i.path}:{i.lineno} {i.module}" for i in census.imports)


def render(census: Census, verbose: bool = False) -> str:
    """Human-readable report. Deterministic ordering throughout."""

    lines: list[str] = []
    discrepancies = compare(census)
    by_layer = census.owner_count_by_layer
    prefixes = census.calls_by_prefix

    lines.append("certified census check - src/hermes (read-only)")
    lines.append("")
    lines.append(f"{'figure':<44} {'certified':>9} {'measured':>9}  status")
    lines.append("-" * 78)

    def row(label: str, expected: int, actual: int) -> None:
        lines.append(
            f"{label:<44} {expected:>9} {actual:>9}  {'OK' if expected == actual else 'MISMATCH'}"
        )

    row("executed transaction-control calls", CERTIFIED_CONTROL_CALLS, len(census.control_calls))
    row(
        "acquisition owners (persistence)",
        CERTIFIED_OWNERS_BY_LAYER["persistence"],
        by_layer.get("persistence", 0),
    )
    row("acquisition owners (gateway)", CERTIFIED_OWNERS_BY_LAYER["gateway"], by_layer.get("gateway", 0))
    row(
        "acquisition owners (Controller)",
        CERTIFIED_OWNERS_BY_LAYER["controller"],
        by_layer.get("controller", 0),
    )
    row("acquisition owners (total)", CERTIFIED_OWNERS_TOTAL, census.owner_count)
    row(
        "rollback-only participants",
        CERTIFIED_ROLLBACK_ONLY_PARTICIPANTS,
        len(census.rollback_only_participants),
    )
    row(
        "persistence->research import statements",
        CERTIFIED_PERSISTENCE_TO_RESEARCH_IMPORTS,
        len(census.imports),
    )
    row("control calls outside certified layers", 0, len(census.foreign_layer_calls))

    lines.append("")
    lines.append(
        "control calls by statement: "
        + ", ".join(f"{name} {count}" for name, count in prefixes.items() if count)
    )
    lines.append(
        f"owners by layer: persistence {by_layer.get('persistence', 0)}, "
        f"gateway {by_layer.get('gateway', 0)}, "
        f"Controller {by_layer.get('controller', 0)}"
    )

    if verbose:
        lines.append("")
        lines.append("acquisition owners (class-qualified, with BEGIN/COMMIT/ROLLBACK):")
        for owner in census.owners:
            lines.append(
                f"  {owner.layer:<12} {owner.path}:{owner.name} "
                f"({owner.begin}B/{owner.commit}C/{owner.rollback}R)"
            )
        lines.append("")
        lines.append("participants (control calls, no acquisition):")
        for participant in census.participants:
            lines.append(
                f"  {participant.layer:<12} {participant.path}:{participant.name} "
                f"({participant.begin}B/{participant.commit}C/{participant.rollback}R)"
            )
        lines.append("")
        lines.append("persistence->research import statements:")
        for site in census.imports:
            lines.append(f"  {site.path}:{site.lineno} {site.module}")

    lines.append("")
    if not discrepancies:
        lines.append("PASS - every certified figure is reproduced exactly.")
    else:
        lines.append(f"FAIL - {len(discrepancies)} certified figure(s) not reproduced:")
        for item in discrepancies:
            lines.append(
                f"  - {item.figure}: certified {item.expected}, measured {item.actual}"
                f" (delta {item.actual - item.expected:+d})"
            )
            if item.detail:
                lines.append(f"      {item.detail}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Re-derive and verify the certified physical census (read-only)."
    )
    parser.add_argument(
        "--repo-root",
        default=str(pathlib.Path(__file__).resolve().parents[1]),
        help="checkout root to measure (default: the repository containing this script)",
    )
    parser.add_argument("--verbose", action="store_true", help="print the full owner/import tables")
    args = parser.parse_args(argv)

    census = analyse(pathlib.Path(args.repo_root))
    print(render(census, verbose=args.verbose))
    return 1 if compare(census) else 0


if __name__ == "__main__":
    sys.exit(main())
